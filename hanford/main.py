"""Entry point: starts TUI + orchestrator in the same asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from hanford.channels.channel_manager import ChannelManager
from hanford.channels.telegram_channel import TelegramChannel
from hanford.channels.tui_channel import TUIChannel
from hanford.channels.whatsapp_channel import WhatsAppChannel
from hanford.config import get_config
from hanford.database import close_db, init_db
from hanford.orchestrator import Orchestrator
from hanford.tui.app import HanfordApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(
            str(__import__("pathlib").Path.home() / ".hanford" / "hanford.log"),
            mode="a",
        ),
    ],
)
logger = logging.getLogger(__name__)


async def _async_main() -> None:
    """
    Core async bootstrap:
    1. Initialize database
    2. Build channels (TUI always present; Telegram/WhatsApp if configured)
    3. Build ChannelManager
    4. Build Orchestrator
    5. Run TUI app concurrently with orchestrator
    """
    config = get_config()

    # Ensure ~/.hanford directory exists
    config.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize database (create tables)
    await init_db()

    # --- Build channels ---

    # TUI channel is always available
    tui_channel = TUIChannel()

    # Telegram channel (optional)
    telegram_channel: TelegramChannel | None = None
    if config.telegram_bot_token:
        telegram_channel = TelegramChannel(config)
        logger.info("Telegram channel available.")

    # WhatsApp channel (optional)
    whatsapp_channel: WhatsAppChannel | None = None
    if config.whatsapp_configured:
        whatsapp_channel = WhatsAppChannel(config)
        logger.info("WhatsApp channel available.")

    # --- Build ChannelManager ---
    channel_manager = ChannelManager(
        tui=tui_channel,
        telegram=telegram_channel,
        whatsapp=whatsapp_channel,
    )

    # --- Build Orchestrator ---
    orchestrator = Orchestrator(
        config=config,
        channel_manager=channel_manager,
    )

    # --- Build TUI app ---
    app = HanfordApp()
    app._tui_channel = tui_channel
    tui_channel.bind_app(app)

    # --- Start orchestrator ---
    await orchestrator.start()

    # --- Run TUI app ---
    # The TUI app runs in the same event loop.
    # When the app exits (user presses q or Ctrl+C), we shut down.
    try:
        await app.run_async()
    except asyncio.CancelledError:
        pass
    finally:
        # Graceful shutdown
        logger.info("Shutting down Hanford...")
        await orchestrator.stop()
        await close_db()
        logger.info("Hanford stopped.")


def run() -> None:
    """Synchronous entry point for the `hanford` CLI command."""
    # Ensure ~/.hanford directory exists for logs
    import pathlib

    log_dir = pathlib.Path.home() / ".hanford"
    log_dir.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        print("\nHanford stopped.")
        sys.exit(0)


if __name__ == "__main__":
    run()
