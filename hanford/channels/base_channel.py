"""Abstract BaseChannel — the core I/O interface all channels implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from hanford.models.pending_action import PendingAction


class BaseChannel(ABC):
    """
    All channels implement this interface.
    The orchestrator only ever calls these methods — never channel-specific code.
    """

    def __init__(self) -> None:
        self._on_message: Callable[[str], Awaitable[None]] | None = None

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return the channel identifier: 'tui', 'telegram', or 'whatsapp'."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Begin listening for inbound messages and/or render UI."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop. Called before switching to another channel."""
        ...

    @abstractmethod
    async def send_notification(self, message: str) -> None:
        """
        Send a plain informational message to the user.
        e.g. "AT&T call complete. Saved $24/mo."
        """
        ...

    @abstractmethod
    async def request_approval(self, action: PendingAction) -> None:
        """
        Surface an action card to the user.
        Does NOT wait for response — approval comes back via on_user_message callback.
        Formats the action card appropriately for the channel.
        """
        ...

    @abstractmethod
    async def send_status(self, status_summary: str) -> None:
        """Respond to a STATUS_REQUEST intent."""
        ...

    def set_message_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """
        Orchestrator registers this callback on startup.
        Channel calls it whenever the user sends a message.
        All messages route through IntentRouter before any action is taken.
        """
        self._on_message = callback

    async def _emit_message(self, text: str) -> None:
        """Helper: forward a user message to the registered callback."""
        if self._on_message:
            await self._on_message(text)
