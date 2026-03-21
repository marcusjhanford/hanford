"""ChannelManager — owns the active channel, handles switching, persists state."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import select

from hanford.channels.base_channel import BaseChannel
from hanford.database import get_session
from hanford.models.channel_state import ChannelState
from hanford.models.pending_action import PendingAction

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Owns the active channel. All orchestrator I/O goes through this class.
    Handles channel switching atomically.
    Persists active channel to DB so restarts resume in the correct channel.

    The orchestrator NEVER references TUI or Telegram directly — only
    ever through ChannelManager.
    """

    def __init__(
        self,
        tui: BaseChannel,
        telegram: BaseChannel | None = None,
        whatsapp: BaseChannel | None = None,
    ) -> None:
        self._channels: dict[str, BaseChannel | None] = {
            "tui": tui,
            "telegram": telegram,
            "whatsapp": whatsapp,
        }
        self._active: BaseChannel = tui
        self._message_callback: Callable[[str], Awaitable[None]] | None = None

    @property
    def active_channel(self) -> BaseChannel:
        return self._active

    @property
    def active_channel_name(self) -> str:
        return self._active.channel_name

    def set_message_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Register the orchestrator's message callback on ALL channels."""
        self._message_callback = callback
        for channel in self._channels.values():
            if channel is not None:
                channel.set_message_callback(callback)

    async def restore_from_db(self) -> None:
        """
        On startup, check ChannelState table. If last active channel was
        telegram/whatsapp and credentials are configured, start in that
        channel instead of TUI.
        """
        session = await get_session()
        try:
            stmt = select(ChannelState).where(ChannelState.id == 1)
            result = await session.execute(stmt)
            state = result.scalar_one_or_none()

            if state and state.active_channel != "tui":
                target = self._channels.get(state.active_channel)
                if target is not None:
                    logger.info("Restoring channel from DB: %s", state.active_channel)
                    self._active = target
                    return

            # Default to TUI
            self._active = self._channels["tui"]  # type: ignore
        finally:
            await session.close()

    async def switch_to(self, channel_name: str) -> bool:
        """
        Switch to a different channel atomically.

        1. Validate target channel is configured (API keys exist)
        2. Call self._active.stop()
        3. Update ChannelState in DB
        4. Set self._active = target channel
        5. Call self._active.start()
        6. Send confirmation

        Returns True on success, False on failure.
        """
        # Validate target exists and is configured
        target = self._channels.get(channel_name)
        if target is None:
            await self._active.send_notification(
                f"{channel_name.title()} is not configured. "
                f"Add the required API keys to your .env file first."
            )
            return False

        if channel_name == self._active.channel_name:
            await self._active.send_notification(f"Already on {channel_name}.")
            return False

        old_channel_name = self._active.channel_name
        logger.info("Switching channel: %s -> %s", old_channel_name, channel_name)

        # Stop current channel
        await self._active.stop()

        # Update DB
        await self._persist_channel_state(channel_name, "user_command")

        # Activate new channel
        self._active = target
        await self._active.start()

        # Confirm on the new channel
        await self._active.send_notification(
            f"Switched to {channel_name}. I'll reach you here from now on."
        )

        return True

    async def start_active(self) -> None:
        """Start the active channel (called during boot)."""
        await self._active.start()

    async def stop_active(self) -> None:
        """Stop the active channel (called during shutdown)."""
        await self._active.stop()

    # --- Delegate all I/O to the active channel ---

    async def send_notification(self, message: str) -> None:
        await self._active.send_notification(message)

    async def request_approval(self, action: PendingAction) -> None:
        await self._active.request_approval(action)

    async def send_status(self, summary: str) -> None:
        await self._active.send_status(summary)

    # --- Persistence ---

    async def _persist_channel_state(self, channel_name: str, switched_by: str) -> None:
        """Update or insert the single-row ChannelState record."""
        session = await get_session()
        try:
            stmt = select(ChannelState).where(ChannelState.id == 1)
            result = await session.execute(stmt)
            state = result.scalar_one_or_none()

            if state:
                state.active_channel = channel_name
                state.switched_at = datetime.utcnow()
                state.switched_by = switched_by
            else:
                state = ChannelState(
                    id=1,
                    active_channel=channel_name,
                    switched_at=datetime.utcnow(),
                    switched_by=switched_by,
                )
                session.add(state)

            await session.commit()
            logger.info(
                "Channel state persisted: %s (by %s)", channel_name, switched_by
            )
        except Exception as exc:
            await session.rollback()
            logger.error("Failed to persist channel state: %s", exc)
        finally:
            await session.close()
