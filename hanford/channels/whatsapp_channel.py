"""WhatsApp channel — Twilio WhatsApp API with aiohttp webhook server."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import parse_qs

from hanford.channels.base_channel import BaseChannel
from hanford.config import Config
from hanford.models.pending_action import PendingAction

logger = logging.getLogger(__name__)


class WhatsAppChannel(BaseChannel):
    """
    Uses Twilio WhatsApp API (Twilio Sandbox for dev, production number for prod).
    Runs a lightweight aiohttp webhook server to receive inbound messages.
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._site: Any = None
        self._runner: Any = None
        self._running = False

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    async def start(self) -> None:
        """
        Start the aiohttp webhook server for inbound WhatsApp messages.
        User must expose this port (ngrok for dev, reverse proxy for prod).
        """
        try:
            from aiohttp import web
        except ImportError:
            logger.error("aiohttp not installed. Run: pip install aiohttp")
            return

        app = web.Application()
        app.router.add_post("/webhook/whatsapp", self._handle_webhook)
        app.router.add_get("/webhook/whatsapp", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            host="0.0.0.0",
            port=self._config.whatsapp_webhook_port,
        )
        await self._site.start()
        self._running = True
        logger.info(
            "WhatsApp webhook server started on port %d.",
            self._config.whatsapp_webhook_port,
        )

    async def stop(self) -> None:
        """Stop the webhook server."""
        self._running = False
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        logger.info("WhatsApp channel stopped.")

    async def send_notification(self, message: str) -> None:
        """Send a WhatsApp message via Twilio REST API."""
        if not self._config.user_whatsapp_number:
            logger.warning("User WhatsApp number not configured.")
            return

        loop = asyncio.get_running_loop()
        try:
            from twilio.rest import Client

            client = Client(
                self._config.twilio_account_sid,
                self._config.twilio_auth_token,
            )

            await loop.run_in_executor(
                None,
                lambda: client.messages.create(
                    from_=self._config.twilio_whatsapp_from,
                    to=f"whatsapp:{self._config.user_whatsapp_number}",
                    body=message,
                ),
            )
        except ImportError:
            logger.error("twilio not installed. Run: pip install twilio")
        except Exception as exc:
            logger.error("WhatsApp send_notification error: %s", exc)

    async def request_approval(self, action: PendingAction) -> None:
        """
        Send a formatted WhatsApp message with numbered options.
        No interactive buttons (WhatsApp API limitation without Business API).

        Example:
          AT&T Bill -- $89.00
          37% above your usual $65. Due March 18.
          Proposed: Call AT&T and negotiate back to ~$65/mo.
          Reply *1* to approve or *2* to dismiss.
        """
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

        message = (
            f"*{provider_name} Bill -- ${current_amount:.2f}*\n"
            f"{deviation_pct}% above your usual ${baseline_amount:.2f}. Due {due_date}.\n\n"
            f"*Proposed:* {action.proposed_action_summary}\n\n"
            f"Reply *1* to approve or *2* to dismiss."
        )

        await self.send_notification(message)

    async def send_status(self, status_summary: str) -> None:
        """Send a status summary via WhatsApp."""
        await self.send_notification(f"*Status:*\n{status_summary}")

    # --- Webhook handlers ---

    async def _handle_webhook(self, request: Any) -> Any:
        """Handle inbound WhatsApp messages from Twilio webhook."""
        from aiohttp import web

        try:
            body = await request.text()
            params = parse_qs(body)

            # Twilio sends form-encoded data
            from_number = params.get("From", [""])[0]
            message_body = params.get("Body", [""])[0].strip()

            # Verify the message is from our user
            expected_from = f"whatsapp:{self._config.user_whatsapp_number}"
            if from_number != expected_from:
                logger.warning(
                    "WhatsApp message from unexpected number: %s", from_number
                )
                return web.Response(
                    text='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                    content_type="text/xml",
                )

            if message_body:
                # Route through intent router via the callback
                await self._emit_message(message_body)

            # Return empty TwiML response
            return web.Response(
                text='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                content_type="text/xml",
            )

        except Exception as exc:
            logger.error("WhatsApp webhook error: %s", exc)
            return web.Response(status=500, text="Internal Server Error")

    async def _handle_health(self, request: Any) -> Any:
        """Health check endpoint for the webhook server."""
        from aiohttp import web

        return web.Response(text="OK", content_type="text/plain")
