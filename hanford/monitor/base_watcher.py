"""Abstract base class for all email/message watchers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine


class BaseWatcher(ABC):
    """
    Interface for background watchers. Each watcher monitors a source
    (Gmail, IMAP, etc.) and fires callbacks when relevant messages arrive.

    Designed for v0.2 extensibility: adding IMAPWatcher requires only
    implementing this interface and updating config to select it.
    """

    @abstractmethod
    async def start(
        self,
        on_bill_email: Callable[..., Coroutine[Any, Any, None]],
        on_directive_match: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """
        Begin polling / watching for new messages.

        Args:
            on_bill_email: Callback fired when a bill-related email is detected.
                Signature: (provider_slug: str, message_id: str, subject: str, body: str)
            on_directive_match: Callback fired when an email matches an active UserDirective.
                Signature: (directive_id: int, message_subject: str, message_snippet: str)
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the watcher loop."""
        ...

    @abstractmethod
    async def force_sync(self) -> None:
        """Force an immediate poll/sync (used by TUI refresh keybinding)."""
        ...
