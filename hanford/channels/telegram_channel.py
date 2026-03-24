"""Telegram channel — python-telegram-bot async polling mode."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from hanford.channels.base_channel import BaseChannel
from hanford.config import Config
from hanford.models.pending_action import PendingAction

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    """
    Uses python-telegram-bot (async version).
    Runs a polling loop (default for self-hosted).
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._application: Any = None
        self._running = False
        self._poll_task: asyncio.Task | None = None

    @property
    def channel_name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        """Start the Telegram bot polling. Register message handler."""
        if not self._config.telegram_bot_token:
            logger.warning("Telegram bot token not configured.")
            return

        try:
            from telegram import Update
            from telegram.ext import (
                Application,
                CallbackQueryHandler,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            logger.error(
                "python-telegram-bot not installed. Run: pip install python-telegram-bot"
            )
            return

        self._application = (
            Application.builder().token(self._config.telegram_bot_token).build()
        )

        # Register handlers
        self._application.add_handler(
            CommandHandler("start", self._handle_start_command)
        )
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self._application.add_handler(CallbackQueryHandler(self._handle_callback))

        self._running = True
        # Initialize and start polling
        await self._application.initialize()
        await self._application.start()
        self._poll_task = asyncio.create_task(self._run_polling())
        logger.info("Telegram channel started (polling mode).")

    async def _run_polling(self) -> None:
        """Run the Telegram polling updater."""
        try:
            updater = self._application.updater
            await updater.start_polling(drop_pending_updates=True)
            # Keep running until stopped
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Telegram polling error: %s", exc)

    async def stop(self) -> None:
        """Stop the Telegram polling loop."""
        self._running = False
        if self._application:
            try:
                if self._application.updater and self._application.updater.running:
                    await self._application.updater.stop()
                await self._application.stop()
                await self._application.shutdown()
            except Exception as exc:
                logger.error("Error stopping Telegram: %s", exc)
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        self._application = None
        logger.info("Telegram channel stopped.")

    async def send_notification(self, message: str) -> None:
        """Send a message to the configured Telegram chat."""
        if not self._config.telegram_chat_id:
            logger.warning("Telegram chat ID not configured.")
            return

        try:
            from telegram import Bot

            bot = Bot(token=self._config.telegram_bot_token)
            await bot.send_message(
                chat_id=int(self._config.telegram_chat_id),
                text=message,
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.error("Telegram send_notification error: %s", exc)

    async def request_approval(self, action: PendingAction) -> None:
        """
        Send a formatted message with inline keyboard buttons.

        Example:
          AT&T Bill -- $89.00
          37% above your usual $65. Due March 18.
          Proposed: Call AT&T and negotiate back to ~$65/mo.
          [Approve]  [Dismiss]
        """
        if not self._config.telegram_chat_id:
            return

        try:
            from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

            # Parse context for display
            context = {}
            try:
                context = json.loads(action.context_json) if action.context_json else {}
            except json.JSONDecodeError:
                pass

            provider_name = context.get("provider_name", "Provider")
            current_amount = context.get("current_amount", 0)
            baseline_amount = context.get("baseline_amount", 0)
            due_date = context.get("due_date", "upcoming")

            deviation_pct = 0
            if baseline_amount > 0:
                deviation_pct = round(
                    ((current_amount - baseline_amount) / baseline_amount) * 100
                )

            text = (
                f"*{provider_name} Bill -- ${current_amount:.2f}*\n"
                f"{deviation_pct}% above your usual ${baseline_amount:.2f}. Due {due_date}.\n\n"
                f"*Proposed:* {action.proposed_action_summary}"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Approve", callback_data=f"approve:{action.id}"
                        ),
                        InlineKeyboardButton(
                            "Dismiss", callback_data=f"reject:{action.id}"
                        ),
                    ]
                ]
            )

            bot = Bot(token=self._config.telegram_bot_token)
            await bot.send_message(
                chat_id=int(self._config.telegram_chat_id),
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as exc:
            logger.error("Telegram request_approval error: %s", exc)

    async def send_status(self, status_summary: str) -> None:
        """Send a status summary to Telegram."""
        await self.send_notification(f"*Status:*\n{status_summary}")

    # --- Handlers ---

    async def _handle_start_command(self, update: Any, context: Any) -> None:
        """Handle /start command. Prints chat ID for setup."""
        chat_id = update.effective_chat.id
        await update.message.reply_text(
            f"Hanford is connected.\n\n"
            f"Your Chat ID: `{chat_id}`\n\n"
            f"Add this to your .env file as TELEGRAM_CHAT_ID={chat_id}",
            parse_mode="Markdown",
        )

    async def _handle_message(self, update: Any, context: Any) -> None:
        """Handle incoming text messages. Route through IntentRouter."""
        if not update.message or not update.message.text:
            return

        # Only accept messages from the configured chat
        if str(update.effective_chat.id) != self._config.telegram_chat_id:
            return

        text = update.message.text.strip()
        if text:
            await self._emit_message(text)

    async def _handle_callback(self, update: Any, context: Any) -> None:
        """Handle inline keyboard button callbacks (approve/reject)."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        data = query.data
        if data.startswith("approve:"):
            await self._emit_message("yes")
        elif data.startswith("reject:"):
            await self._emit_message("no")
