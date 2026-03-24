"""Notification list widget — displays recent notifications in the dashboard."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


class NotificationItem(Static):
    """A single notification entry."""

    DEFAULT_CSS = """
    NotificationItem {
        padding: 0 1;
        margin: 0 0 0 0;
        height: auto;
    }
    """

    def __init__(self, text: str, timestamp: str | None = None) -> None:
        self._text = text
        self._timestamp = timestamp or datetime.now().strftime("%H:%M")
        super().__init__(f"[dim]{self._timestamp}[/dim] {self._text}")


class NotificationList(Widget):
    """
    Scrollable list of recent notifications. New items appear at the top.
    Maximum of 50 retained items.
    """

    DEFAULT_CSS = """
    NotificationList {
        height: auto;
        max-height: 12;
        border: solid $primary;
        padding: 0;
    }
    """

    MAX_ITEMS = 50

    class NotificationAdded(Message):
        """Posted when a new notification is added."""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="notification-scroll")

    def add_notification(self, text: str) -> None:
        """Add a new notification to the top of the list."""
        scroll = self.query_one("#notification-scroll", VerticalScroll)
        item = NotificationItem(text)
        scroll.mount(item, before=0)

        # Trim to max items
        children = list(scroll.children)
        while len(children) > self.MAX_ITEMS:
            children[-1].remove()
            children = children[:-1]

        self.post_message(self.NotificationAdded(text))

    def clear(self) -> None:
        """Remove all notifications."""
        scroll = self.query_one("#notification-scroll", VerticalScroll)
        scroll.remove_children()
