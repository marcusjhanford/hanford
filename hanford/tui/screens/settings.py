"""Settings screen — view and edit configuration values."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from hanford.config import get_config


class SettingsField(Static):
    """A single settings field with label and masked value."""

    DEFAULT_CSS = """
    SettingsField {
        height: auto;
        padding: 0 2;
        margin: 0 0 0 0;
    }
    """

    def __init__(self, label: str, value: str, masked: bool = True) -> None:
        self._label = label
        self._value = value
        self._masked = masked

        display_value = (
            self._mask_value(value)
            if masked and value
            else (value or "[dim]not set[/dim]")
        )
        super().__init__(f"  {label + ':':<28} {display_value}")

    @staticmethod
    def _mask_value(value: str) -> str:
        """Show first 4 and last 4 characters, mask the rest."""
        if len(value) <= 8:
            return "*" * len(value)
        return value[:4] + "*" * (len(value) - 8) + value[-4:]


class SettingsScreen(Screen):
    """
    Settings screen showing API keys, connected accounts,
    messaging channels, monitoring config, and user info.
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
    ]

    DEFAULT_CSS = """
    SettingsScreen {
        layout: vertical;
    }

    #settings-content {
        padding: 1 2;
        height: 1fr;
    }

    .settings-section-header {
        text-style: bold;
        padding: 1 0 0 0;
        color: $accent;
    }

    .settings-section {
        height: auto;
        padding: 0 0 0 0;
    }

    #settings-footer {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $primary-darken-2;
    }
    """

    def compose(self) -> ComposeResult:
        cfg = get_config()

        yield Header(show_clock=True)
        with VerticalScroll(id="settings-content"):
            # LLM Provider
            yield Static("[bold]LLM PROVIDER[/bold]", classes="settings-section-header")
            with Vertical(classes="settings-section"):
                provider = cfg.llm_provider.upper()
                yield Static(f"  {'Active Provider:':<28} [bold]{provider}[/bold]")
                if cfg.llm_provider == "openai":
                    yield SettingsField("OpenAI API Key", cfg.openai_api_key)
                    yield SettingsField("OpenAI Model", cfg.openai_model, masked=False)
                    yield SettingsField(
                        "OpenAI Base URL", cfg.openai_base_url, masked=False
                    )
                else:
                    yield SettingsField("Anthropic API Key", cfg.anthropic_api_key)
                    yield SettingsField(
                        "Anthropic Model", cfg.anthropic_model, masked=False
                    )

            # Vapi
            yield Static(
                "[bold]VAPI (PHONE CALLS)[/bold]", classes="settings-section-header"
            )
            with Vertical(classes="settings-section"):
                yield SettingsField("Vapi API Key", cfg.vapi_api_key)
                yield SettingsField("Vapi Phone Number ID", cfg.vapi_phone_number_id)

            # Connected Accounts
            yield Static(
                "[bold]CONNECTED ACCOUNTS[/bold]", classes="settings-section-header"
            )
            with Vertical(classes="settings-section"):
                gmail_status = (
                    "[green]connected[/green]"
                    if cfg.gmail_token_path.exists()
                    else "[red]not connected[/red]"
                )
                yield Static(f"  {'Gmail:':<28} {gmail_status}")

            # Messaging Channels
            yield Static(
                "[bold]MESSAGING CHANNELS[/bold]", classes="settings-section-header"
            )
            with Vertical(classes="settings-section"):
                yield SettingsField("Telegram Bot Token", cfg.telegram_bot_token)
                yield SettingsField("Telegram Chat ID", cfg.telegram_chat_id)
                tg_status = (
                    "[green]configured[/green]"
                    if cfg.telegram_configured
                    else "[dim]not configured[/dim]"
                )
                yield Static(f"  {'Telegram Status:':<28} {tg_status}")
                yield Static("")
                yield SettingsField("Twilio Account SID", cfg.twilio_account_sid)
                yield SettingsField(
                    "WhatsApp Phone", cfg.user_whatsapp_number, masked=False
                )
                wa_status = (
                    "[green]configured[/green]"
                    if cfg.whatsapp_configured
                    else "[dim]not configured[/dim]"
                )
                yield Static(f"  {'WhatsApp Status:':<28} {wa_status}")

            # Active Channel
            yield Static(
                "[bold]ACTIVE CHANNEL[/bold]", classes="settings-section-header"
            )
            with Vertical(classes="settings-section"):
                yield Static(
                    f"  {'Current:':<28} [bold]{self._get_active_channel()}[/bold]"
                )

            # Monitoring
            yield Static("[bold]MONITORING[/bold]", classes="settings-section-header")
            with Vertical(classes="settings-section"):
                yield Static(
                    f"  {'Poll interval:':<28} {cfg.gmail_poll_interval_seconds // 60} minutes"
                )
                yield Static(
                    f"  {'Anomaly threshold:':<28} {int(cfg.anomaly_threshold * 100)}%"
                )
                yield Static(
                    f"  {'Max concurrent calls:':<28} {cfg.max_concurrent_calls}"
                )

            # User Info
            yield Static(
                "[bold]YOUR INFO (used in calls)[/bold]",
                classes="settings-section-header",
            )
            with Vertical(classes="settings-section"):
                yield Static(f"  {'Name:':<28} {cfg.user_name or '[dim]not set[/dim]'}")

            # Database
            yield Static("[bold]DATABASE[/bold]", classes="settings-section-header")
            with Vertical(classes="settings-section"):
                yield Static(f"  {'Path:':<28} {cfg.database_path}")

            yield Static("")
            yield Static(
                "[dim]To edit settings, modify your .env file and restart Hanford.[/dim]",
            )

        yield Footer()

    def action_go_back(self) -> None:
        """Return to the dashboard."""
        self.app.pop_screen()

    def _get_active_channel(self) -> str:
        """Get the current active channel name from the app."""
        try:
            return getattr(self.app, "_active_channel_name", "TUI").upper()
        except Exception:
            return "TUI"
