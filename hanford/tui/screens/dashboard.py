"""Dashboard screen — main TUI view with pending actions, history, directives."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from hanford.tui.widgets.history_table import HistoryTable
from hanford.tui.widgets.input_bar import InputBar
from hanford.tui.widgets.notification_list import NotificationList
from hanford.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from hanford.models.pending_action import PendingAction
    from hanford.models.user_directive import UserDirective


class PendingActionCard(Static):
    """A single pending action card displayed in the dashboard."""

    DEFAULT_CSS = """
    PendingActionCard {
        border: heavy $warning;
        padding: 1 2;
        margin: 0 0 1 0;
        height: auto;
        background: $surface;
    }
    """

    def __init__(self, action: PendingAction) -> None:
        self._action = action
        context = {}
        try:
            context = json.loads(action.context_json) if action.context_json else {}
        except (json.JSONDecodeError, TypeError):
            pass

        provider_name = context.get("provider_name", "Provider")
        current_amount = context.get("current_amount", 0)
        baseline_amount = context.get("baseline_amount", 0)
        due_date = context.get("due_date", "upcoming")
        deviation_pct = context.get("deviation_pct", 0)

        text = (
            f"[bold yellow]>> {provider_name} Bill -- ${current_amount:.2f}[/bold yellow]\n"
            f"   {deviation_pct}% above your usual ${baseline_amount:.2f}. Due {due_date}.\n"
            f"   [Y] Call {provider_name}    [N] Dismiss"
        )
        super().__init__(text)


class DirectiveCard(Static):
    """A single active directive shown in the WATCHING section."""

    DEFAULT_CSS = """
    DirectiveCard {
        padding: 0 2;
        height: auto;
    }
    """

    def __init__(self, directive: UserDirective) -> None:
        self._directive = directive
        super().__init__(f"  [cyan]>>[/cyan] {directive.parsed_intent}")


class DashboardScreen(Screen):
    """
    Main dashboard screen.

    Layout:
    - PENDING section (action cards)
    - RECENT ACTIVITY section (history table)
    - WATCHING section (active directives)
    - Input bar (always at bottom)
    - Status bar (very bottom)
    """

    BINDINGS = [
        ("y", "approve_action", "Approve"),
        ("n", "dismiss_action", "Dismiss"),
        ("v", "view_detail", "View"),
        ("s", "open_settings", "Settings"),
        ("r", "force_refresh", "Refresh"),
        ("slash", "focus_input", "Input"),
        ("escape", "blur_input", "Blur"),
        ("q", "quit_app", "Quit"),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }

    #dashboard-content {
        height: 1fr;
        padding: 0 1;
    }

    .section-header {
        text-style: bold;
        padding: 1 0 0 0;
        color: $text;
    }

    #pending-section {
        height: auto;
        max-height: 40%;
    }

    #history-section {
        height: auto;
        max-height: 30%;
    }

    #watching-section {
        height: auto;
        max-height: 20%;
    }

    #notification-section {
        height: auto;
        max-height: 20%;
    }

    #inactive-message {
        display: none;
        height: 100%;
        content-align: center middle;
        text-align: center;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="dashboard-content"):
            # Notifications
            yield Static("[bold]NOTIFICATIONS[/bold]", classes="section-header")
            yield NotificationList(id="notifications")

            # Pending actions
            yield Static(
                "[bold]PENDING[/bold]", classes="section-header", id="pending-header"
            )
            yield Container(id="pending-section")

            # Recent activity
            yield Static("[bold]RECENT ACTIVITY[/bold]", classes="section-header")
            yield HistoryTable(id="history")

            # Active directives / watching
            yield Static(
                "[bold]WATCHING[/bold]", classes="section-header", id="watching-header"
            )
            yield Container(id="watching-section")

        # Inactive mode overlay (hidden by default)
        yield Static(
            "[bold]Hanford is running in messaging mode.[/bold]\n"
            "This terminal is inactive.\n\n"
            "Send 'switch back to device' from your messaging app to return.\n"
            "Press Ctrl+C to quit Hanford entirely.",
            id="inactive-message",
        )

        yield InputBar(id="input-bar")
        yield StatusBar(id="status-bar")
        yield Footer()

    def action_approve_action(self) -> None:
        """Keybinding: approve the top pending action."""
        self._emit_input("y")

    def action_dismiss_action(self) -> None:
        """Keybinding: dismiss the top pending action."""
        self._emit_input("n")

    def action_view_detail(self) -> None:
        """Keybinding: view detail of selected item."""
        # Placeholder — would open a detail view in a fuller implementation
        self.notify("View detail not yet available for this item.")

    def action_open_settings(self) -> None:
        """Keybinding: open settings screen."""
        from hanford.tui.screens.settings import SettingsScreen

        self.app.push_screen(SettingsScreen())

    def action_force_refresh(self) -> None:
        """Keybinding: force Gmail sync."""
        self._emit_input("/refresh")
        self.notify("Forcing Gmail sync...")

    def action_focus_input(self) -> None:
        """Keybinding: focus the input bar."""
        try:
            bar = self.query_one("#input-bar", InputBar)
            bar.focus_input()
        except Exception:
            pass

    def action_blur_input(self) -> None:
        """Keybinding: blur the input bar / close modal."""
        try:
            bar = self.query_one("#input-bar", InputBar)
            bar.blur_input()
        except Exception:
            pass

    def action_quit_app(self) -> None:
        """Keybinding: quit Hanford entirely."""
        self.app.exit()

    def _emit_input(self, text: str) -> None:
        """Simulate input submission through the input bar's message system."""
        bar = self.query_one("#input-bar", InputBar)
        bar.post_message(InputBar.MessageSubmitted(text))

    # --- Public methods called by HanfordApp ---

    def add_notification(self, text: str) -> None:
        """Add a notification to the notification list."""
        try:
            notif_list = self.query_one("#notifications", NotificationList)
            notif_list.add_notification(text)
        except Exception:
            pass

    def update_pending_actions(self, actions: list[PendingAction]) -> None:
        """Replace pending action cards."""
        try:
            container = self.query_one("#pending-section", Container)
            container.remove_children()
            header = self.query_one("#pending-header", Static)
            header.update(f"[bold]PENDING ({len(actions)})[/bold]")

            for action in actions:
                container.mount(PendingActionCard(action))
        except Exception:
            pass

    def update_history(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Update the history table."""
        try:
            table = self.query_one("#history", HistoryTable)
            table.update_rows(rows)
        except Exception:
            pass

    def update_directives(self, directives: list[UserDirective]) -> None:
        """Update the watching section."""
        try:
            container = self.query_one("#watching-section", Container)
            container.remove_children()
            header = self.query_one("#watching-header", Static)
            header.update(f"[bold]WATCHING ({len(directives)})[/bold]")

            for directive in directives:
                container.mount(DirectiveCard(directive))
        except Exception:
            pass

    def update_status_bar(
        self,
        gmail_active: bool = True,
        channel: str = "TUI",
    ) -> None:
        """Update the status bar."""
        try:
            bar = self.query_one("#status-bar", StatusBar)
            bar.set_gmail_active(gmail_active)
            bar.set_channel(channel)
            bar.update_last_checked()
        except Exception:
            pass

    def show_inactive(self) -> None:
        """Show the inactive mode overlay, hiding the dashboard content."""
        try:
            content = self.query_one("#dashboard-content")
            content.styles.display = "none"
            inactive = self.query_one("#inactive-message")
            inactive.styles.display = "block"
            # Hide input bar
            input_bar = self.query_one("#input-bar")
            input_bar.styles.display = "none"
        except Exception:
            pass

    def show_active(self) -> None:
        """Re-show the dashboard, hiding the inactive overlay."""
        try:
            content = self.query_one("#dashboard-content")
            content.styles.display = "block"
            inactive = self.query_one("#inactive-message")
            inactive.styles.display = "none"
            input_bar = self.query_one("#input-bar")
            input_bar.styles.display = "block"
        except Exception:
            pass
