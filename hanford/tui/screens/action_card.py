"""Action card modal — detailed view of a pending action requiring approval."""

from __future__ import annotations

import json

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from hanford.models.pending_action import PendingAction


class ActionCardModal(ModalScreen[str]):
    """
    Modal screen showing full action details.

    Returns:
        "approve" if user approves
        "reject" if user rejects
        "view" if user wants to view the bill email
    """

    BINDINGS = [
        ("y", "approve", "Approve"),
        ("n", "reject", "Dismiss"),
        ("v", "view_bill", "View Bill"),
        ("escape", "reject", "Close"),
    ]

    DEFAULT_CSS = """
    ActionCardModal {
        align: center middle;
    }

    #action-card-container {
        width: 70;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        border: thick $warning;
        background: $surface;
        padding: 2 3;
    }

    #action-card-title {
        text-style: bold;
        text-align: center;
        padding: 0 0 1 0;
        color: $warning;
    }

    .action-detail-row {
        height: auto;
        padding: 0 0 0 2;
    }

    .action-detail-label {
        width: 20;
        color: $text-muted;
    }

    .action-detail-value {
        width: 1fr;
    }

    #action-proposed {
        padding: 1 2;
        margin: 1 0;
        border: solid $accent;
        height: auto;
    }

    #action-buttons {
        padding: 1 0 0 0;
        height: auto;
        align-horizontal: center;
    }

    #action-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, action: PendingAction) -> None:
        super().__init__()
        self._action = action
        self._context: dict = {}
        try:
            self._context = (
                json.loads(action.context_json) if action.context_json else {}
            )
        except (json.JSONDecodeError, TypeError):
            pass

    def compose(self) -> ComposeResult:
        ctx = self._context
        provider_name = ctx.get("provider_name", "Provider")
        current = ctx.get("current_amount", 0)
        baseline = ctx.get("baseline_amount", 0)
        due = ctx.get("due_date", "upcoming")
        deviation = ctx.get("deviation_pct", 0)
        difference = current - baseline

        with Static(id="action-card-container"):
            yield Static("ACTION REQUIRED", id="action-card-title")
            yield Static("")
            yield Static(
                f"  {provider_name} bill detected", classes="action-detail-row"
            )
            yield Static("")

            with Horizontal(classes="action-detail-row"):
                yield Static("Current bill:", classes="action-detail-label")
                yield Static(f"${current:.2f}", classes="action-detail-value")

            with Horizontal(classes="action-detail-row"):
                yield Static("Your usual:", classes="action-detail-label")
                yield Static(f"~${baseline:.2f}", classes="action-detail-value")

            with Horizontal(classes="action-detail-row"):
                yield Static("Difference:", classes="action-detail-label")
                yield Static(
                    f"+${difference:.2f} ({deviation}% increase)",
                    classes="action-detail-value",
                )

            with Horizontal(classes="action-detail-row"):
                yield Static("Due date:", classes="action-detail-label")
                yield Static(str(due), classes="action-detail-value")

            yield Static("")
            yield Static("[bold]Proposed action:[/bold]", classes="action-detail-row")
            yield Static(
                f"  {self._action.proposed_action_summary}\n"
                f"  Estimated call time: 20-40 minutes.",
                id="action-proposed",
            )

            with Horizontal(id="action-buttons"):
                yield Button("[Y] Approve", variant="success", id="btn-approve")
                yield Button("[N] Dismiss", variant="error", id="btn-reject")
                yield Button("[V] View bill email", variant="default", id="btn-view")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            self.dismiss("approve")
        elif event.button.id == "btn-reject":
            self.dismiss("reject")
        elif event.button.id == "btn-view":
            self.dismiss("view")

    def action_approve(self) -> None:
        self.dismiss("approve")

    def action_reject(self) -> None:
        self.dismiss("reject")

    def action_view_bill(self) -> None:
        self.dismiss("view")
