"""History table widget — displays recent interactions in a formatted table."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable


class HistoryTable(Widget):
    """
    Tabular view of recent interactions (calls, outcomes, savings).
    Shows the last N completed interactions.
    """

    DEFAULT_CSS = """
    HistoryTable {
        height: auto;
        max-height: 10;
        border: solid $primary;
    }
    """

    def compose(self) -> ComposeResult:
        table = DataTable(id="history-data-table")
        table.cursor_type = "row"
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#history-data-table", DataTable)
        table.add_columns("Status", "Provider", "Date", "Outcome")

    def update_rows(self, rows: list[tuple[str, str, str, str]]) -> None:
        """
        Replace table contents with new data.

        Args:
            rows: List of (status_icon, provider_name, date_str, outcome_summary)
        """
        table = self.query_one("#history-data-table", DataTable)
        table.clear()
        for row in rows:
            table.add_row(*row)

    def add_row(
        self, status_icon: str, provider: str, date_str: str, outcome: str
    ) -> None:
        """Add a single row to the table."""
        table = self.query_one("#history-data-table", DataTable)
        table.add_row(status_icon, provider, date_str, outcome)
