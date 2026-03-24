"""Hanford TUI application — Textual-based terminal interface."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from textual.app import App

from hanford.models.pending_action import PendingAction
from hanford.tui.screens.action_card import ActionCardModal
from hanford.tui.screens.dashboard import DashboardScreen
from hanford.tui.widgets.input_bar import InputBar

logger = logging.getLogger(__name__)


class HanfordApp(App):
    """
    The Textual TUI application. UI only — all logic lives in the orchestrator.
    The TUI channel bridges this app to the BaseChannel interface.
    """

    TITLE = "HANFORD"
    SUB_TITLE = "Life Administration Agent"

    CSS = """
    Screen {
        background: $background;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._dashboard: DashboardScreen | None = None
        self._tui_channel: Any = None  # Set by main.py
        self._active_channel_name: str = "TUI"

    def on_mount(self) -> None:
        """Install the dashboard screen on mount."""
        self._dashboard = DashboardScreen()
        self.push_screen(self._dashboard)

    def on_input_bar_message_submitted(
        self, message: InputBar.MessageSubmitted
    ) -> None:
        """Handle messages submitted via the input bar."""
        text = message.text.strip()
        if not text:
            return

        # Handle special commands
        if text == "/refresh":
            self._trigger_refresh()
            return

        # Forward to TUI channel -> orchestrator
        if self._tui_channel:
            asyncio.create_task(self._tui_channel.handle_user_input(text))

    def _trigger_refresh(self) -> None:
        """Trigger a Gmail force sync via the orchestrator."""
        if self._tui_channel and self._tui_channel._on_message:
            asyncio.create_task(self._tui_channel._on_message("/refresh"))

    # --- Methods called by TUIChannel (via call_from_thread) ---

    def post_notification(self, message: str) -> None:
        """Add a notification to the dashboard."""
        if self._dashboard:
            self._dashboard.add_notification(message)

    def show_action_card(self, action: PendingAction) -> None:
        """Show the action card modal for approval."""

        def handle_result(result: str | None) -> None:
            if result == "approve" and self._tui_channel:
                asyncio.create_task(self._tui_channel.handle_user_input("yes"))
            elif result == "reject" and self._tui_channel:
                asyncio.create_task(self._tui_channel.handle_user_input("no"))

        modal = ActionCardModal(action)
        self.push_screen(modal, callback=handle_result)

    def show_inactive_mode(self) -> None:
        """Switch the dashboard to inactive mode (channel switched away from TUI)."""
        if self._dashboard:
            self._dashboard.show_inactive()

    def reactivate_dashboard(self) -> None:
        """Restore the dashboard from inactive mode (switching back to TUI)."""
        if self._dashboard:
            self._dashboard.show_active()

    def update_pending_actions(self, actions: list[PendingAction]) -> None:
        """Update the pending actions display on the dashboard."""
        if self._dashboard:
            self._dashboard.update_pending_actions(actions)

    def update_history(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Update the history table on the dashboard."""
        if self._dashboard:
            self._dashboard.update_history(rows)

    def update_directives(self, directives: list) -> None:
        """Update the watching section on the dashboard."""
        if self._dashboard:
            self._dashboard.update_directives(directives)

    def update_status_bar(
        self, gmail_active: bool = True, channel: str = "TUI"
    ) -> None:
        """Update the status bar."""
        self._active_channel_name = channel
        if self._dashboard:
            self._dashboard.update_status_bar(
                gmail_active=gmail_active, channel=channel
            )
