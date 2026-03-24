"""Input bar widget — natural language input always visible at dashboard bottom."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input


class InputBar(Widget):
    """
    The primary natural language interface. Always visible at the bottom
    of the dashboard. Any message typed here routes through the IntentRouter.
    """

    DEFAULT_CSS = """
    InputBar {
        dock: bottom;
        height: 3;
        padding: 0 1;
    }

    InputBar Input {
        width: 100%;
    }
    """

    class MessageSubmitted(Message):
        """Posted when user submits a message."""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Type a message or command...",
            id="input-bar-field",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission — post message and clear."""
        text = event.value.strip()
        if text:
            self.post_message(self.MessageSubmitted(text))
            event.input.value = ""

    def focus_input(self) -> None:
        """Focus the input field."""
        try:
            inp = self.query_one("#input-bar-field", Input)
            inp.focus()
        except Exception:
            pass

    def blur_input(self) -> None:
        """Remove focus from the input field."""
        try:
            inp = self.query_one("#input-bar-field", Input)
            inp.blur()
        except Exception:
            pass
