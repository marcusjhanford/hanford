"""TUI Channel — bridges the Textual app and the BaseChannel interface."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from hanford.channels.base_channel import BaseChannel
from hanford.models.pending_action import PendingAction

if TYPE_CHECKING:
    from hanford.tui.app import HanfordApp

logger = logging.getLogger(__name__)


class TUIChannel(BaseChannel):
    """
    Thin bridge between the Textual app and the BaseChannel interface.

    - send_notification() -> posts to the notification list widget
    - request_approval() -> triggers the action card modal
    - stop() -> hides TUI, prints inactive message, keeps process alive
    - start() -> re-activates TUI, restores dashboard
    """

    def __init__(self) -> None:
        super().__init__()
        self._app: HanfordApp | None = None
        self._active = False
        self._inactive_message_shown = False

    @property
    def channel_name(self) -> str:
        return "tui"

    def bind_app(self, app: HanfordApp) -> None:
        """Bind the Textual app instance (called once during startup)."""
        self._app = app

    async def start(self) -> None:
        """Activate the TUI channel."""
        self._active = True
        self._inactive_message_shown = False
        if self._app and self._app._running:
            # If switching back to TUI, re-activate the dashboard
            self._app.call_from_thread(self._app.reactivate_dashboard)
        logger.info("TUI channel started.")

    async def stop(self) -> None:
        """
        Deactivate the TUI. Does NOT exit the process.
        Shows an inactive message and keeps the process alive so
        the event loop continues running for other channels.
        """
        self._active = False
        if self._app and not self._inactive_message_shown:
            self._inactive_message_shown = True
            self._app.call_from_thread(self._app.show_inactive_mode)
        logger.info("TUI channel stopped (process stays alive).")

    async def send_notification(self, message: str) -> None:
        """Post a notification to the TUI notification list widget."""
        if not self._active or not self._app:
            return
        self._app.call_from_thread(self._app.post_notification, message)

    async def request_approval(self, action: PendingAction) -> None:
        """Trigger the action card modal in the TUI."""
        if not self._active or not self._app:
            return
        self._app.call_from_thread(self._app.show_action_card, action)

    async def send_status(self, status_summary: str) -> None:
        """Display a status summary in the TUI."""
        if not self._active or not self._app:
            return
        self._app.call_from_thread(
            self._app.post_notification, f"STATUS: {status_summary}"
        )

    async def handle_user_input(self, text: str) -> None:
        """
        Called by the TUI input bar when the user submits text.
        Forwards to the orchestrator via the registered message callback.
        """
        if text.strip():
            await self._emit_message(text.strip())
