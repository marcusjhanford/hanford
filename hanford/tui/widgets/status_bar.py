"""Status bar widget — shows monitoring status, active channel, last check time."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget):
    """
    Bottom status bar showing:
    - Monitoring status (Gmail active/inactive)
    - Active channel (TUI / Telegram / WhatsApp)
    - Last checked timestamp
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }

    StatusBar .status-left {
        width: 1fr;
        content-align-horizontal: left;
    }

    StatusBar .status-right {
        width: auto;
        content-align-horizontal: right;
    }
    """

    gmail_status: reactive[str] = reactive("inactive")
    active_channel: reactive[str] = reactive("TUI")
    last_checked: reactive[str] = reactive("never")

    def compose(self) -> ComposeResult:
        yield Static(self._format_status(), id="status-text")

    def _format_status(self) -> str:
        gmail_indicator = (
            "[green]●[/green]" if self.gmail_status == "active" else "[red]●[/red]"
        )
        return (
            f"  Monitoring: Gmail {gmail_indicator}  |  "
            f"Channel: {self.active_channel}  |  "
            f"Last checked: {self.last_checked}"
        )

    def watch_gmail_status(self) -> None:
        self._refresh_text()

    def watch_active_channel(self) -> None:
        self._refresh_text()

    def watch_last_checked(self) -> None:
        self._refresh_text()

    def _refresh_text(self) -> None:
        try:
            text_widget = self.query_one("#status-text", Static)
            text_widget.update(self._format_status())
        except Exception:
            pass

    def update_last_checked(self) -> None:
        """Update the last checked time to now."""
        self.last_checked = datetime.now().strftime("%H:%M")

    def set_gmail_active(self, active: bool) -> None:
        """Set Gmail monitoring status."""
        self.gmail_status = "active" if active else "inactive"

    def set_channel(self, channel: str) -> None:
        """Set the displayed active channel name."""
        self.active_channel = channel.upper()
