"""Configuration loader. Reads .env and exposes typed config values."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """Load .env from project root, then from ~/.hanford/.env as fallback."""
    project_env = Path(__file__).resolve().parent.parent / ".env"
    home_env = Path.home() / ".hanford" / ".env"
    if project_env.exists():
        load_dotenv(project_env)
    elif home_env.exists():
        load_dotenv(home_env)
    else:
        load_dotenv()


_load_env()


@dataclass(frozen=True)
class Config:
    """Immutable application configuration built from environment variables."""

    # --- LLM ---
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "openai").lower()
    )  # "openai", "anthropic", "ollama", or "vllm"

    # OpenAI
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )

    # Anthropic (Claude)
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )

    # Ollama (Local LLM)
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1"
        )
    )
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2")
    )

    # vLLM (Local LLM Server)
    vllm_base_url: str = field(
        default_factory=lambda: os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    )
    vllm_model: str = field(default_factory=lambda: os.getenv("VLLM_MODEL", ""))
    vllm_api_key: str = field(default_factory=lambda: os.getenv("VLLM_API_KEY", ""))

    # --- Vapi ---
    vapi_api_key: str = field(default_factory=lambda: os.getenv("VAPI_API_KEY", ""))
    vapi_phone_number_id: str = field(
        default_factory=lambda: os.getenv("VAPI_PHONE_NUMBER_ID", "")
    )

    # --- User identity ---
    user_name: str = field(default_factory=lambda: os.getenv("USER_NAME", ""))

    # --- Telegram ---
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )
    telegram_chat_id: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", "")
    )
    telegram_use_webhook: bool = field(
        default_factory=lambda: os.getenv("TELEGRAM_USE_WEBHOOK", "false").lower()
        == "true"
    )

    # --- WhatsApp / Twilio ---
    twilio_account_sid: str = field(
        default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", "")
    )
    twilio_auth_token: str = field(
        default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", "")
    )
    twilio_whatsapp_from: str = field(
        default_factory=lambda: os.getenv(
            "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
        )
    )
    user_whatsapp_number: str = field(
        default_factory=lambda: os.getenv("USER_WHATSAPP_NUMBER", "")
    )
    whatsapp_webhook_port: int = field(
        default_factory=lambda: int(os.getenv("WHATSAPP_WEBHOOK_PORT", "8080"))
    )

    # --- Monitoring ---
    gmail_poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("GMAIL_POLL_INTERVAL_SECONDS", "300"))
    )
    anomaly_threshold: float = field(
        default_factory=lambda: float(os.getenv("ANOMALY_THRESHOLD", "0.15"))
    )
    max_concurrent_calls: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_CALLS", "1"))
    )

    # --- Paths ---
    database_path: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_PATH",
            str(Path.home() / ".hanford" / "hanford.db"),
        )
    )

    # --- Derived helpers ---

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def whatsapp_configured(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_auth_token
            and self.user_whatsapp_number
        )

    @property
    def gmail_credentials_path(self) -> Path:
        return Path.home() / ".hanford" / "credentials.json"

    @property
    def gmail_token_path(self) -> Path:
        return Path.home() / ".hanford" / "gmail_token.json"

    @property
    def resolved_database_path(self) -> Path:
        """Expand ~ and ensure parent directory exists."""
        p = Path(self.database_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def get_config() -> Config:
    """Return a fresh Config instance (re-reads env on each call)."""
    return Config()
