"""Gmail watcher: polls Gmail API for bill emails and directive matches."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from email.utils import parseaddr
from functools import partial
from pathlib import Path
from typing import Any, Callable, Coroutine

from sqlalchemy import select

from hanford.config import Config
from hanford.database import get_session
from hanford.models.provider import Provider
from hanford.models.user_directive import UserDirective
from hanford.monitor.base_watcher import BaseWatcher

logger = logging.getLogger(__name__)


class EmailMessage:
    """Lightweight representation of a Gmail message."""

    def __init__(
        self,
        message_id: str,
        sender: str,
        subject: str,
        body: str,
        snippet: str,
    ) -> None:
        self.message_id = message_id
        self.sender = sender
        self.subject = subject
        self.body = body
        self.snippet = snippet


class GmailWatcher(BaseWatcher):
    """
    Polls Gmail API every GMAIL_POLL_INTERVAL seconds. Uses Gmail history API
    after first sync. On each new email, checks against provider patterns and
    active user directives.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._poll_interval = config.gmail_poll_interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        self._service: Any = None
        self._history_id: str | None = None
        self._on_bill_email: Callable[..., Coroutine[Any, Any, None]] | None = None
        self._on_directive_match: Callable[..., Coroutine[Any, Any, None]] | None = None

    async def start(
        self,
        on_bill_email: Callable[..., Coroutine[Any, Any, None]],
        on_directive_match: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """
        Begin polling Gmail for new messages.

        Two callbacks:
        - on_bill_email: triggers bill parse -> anomaly -> approval flow
          Signature: (provider_slug, message_id, subject, body, snippet)
        - on_directive_match: triggers immediate notification to user
          Signature: (directive_id, message_subject, message_snippet)
        """
        self._on_bill_email = on_bill_email
        self._on_directive_match = on_directive_match
        self._running = True
        self._service = await self._build_gmail_service()

        if self._service is None:
            logger.warning(
                "Gmail credentials not found at %s. Gmail monitoring disabled.",
                self._config.gmail_credentials_path,
            )
            return

        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Gmail watcher started (interval=%ds).", self._poll_interval)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Gmail watcher stopped.")

    async def force_sync(self) -> None:
        """Force an immediate poll (used by TUI refresh keybinding)."""
        if self._service is not None:
            await self._poll_once()

    async def _build_gmail_service(self) -> Any:
        """Build the Gmail API service using OAuth2 credentials."""
        creds_path = self._config.gmail_credentials_path
        token_path = self._config.gmail_token_path

        if not creds_path.exists():
            return None

        loop = asyncio.get_running_loop()

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

            creds = None
            if token_path.exists():
                creds = await loop.run_in_executor(
                    None,
                    partial(
                        Credentials.from_authorized_user_file, str(token_path), SCOPES
                    ),
                )

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    await loop.run_in_executor(None, partial(creds.refresh, Request()))
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(creds_path), SCOPES
                    )
                    creds = await loop.run_in_executor(
                        None, partial(flow.run_local_server, port=0)
                    )

                # Save token for next run
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(creds.to_json())

            service = await loop.run_in_executor(
                None,
                partial(build, "gmail", "v1", credentials=creds, cache_discovery=False),
            )
            return service

        except ImportError:
            logger.error(
                "Google API libraries not installed. Run: pip install google-auth-oauthlib google-api-python-client"
            )
            return None
        except Exception as exc:
            logger.error("Failed to build Gmail service: %s", exc)
            return None

    async def _poll_loop(self) -> None:
        """Main polling loop: runs until stopped."""
        # Initial sync to establish history ID
        await self._initial_sync()

        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                if self._running:
                    await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Gmail poll error: %s", exc)
                await asyncio.sleep(30)  # Back off on errors

    async def _initial_sync(self) -> None:
        """Get the current history ID without processing old messages."""
        loop = asyncio.get_running_loop()
        try:
            profile = await loop.run_in_executor(
                None,
                lambda: self._service.users().getProfile(userId="me").execute(),
            )
            self._history_id = profile.get("historyId")
            logger.info("Gmail initial sync: history_id=%s", self._history_id)
        except Exception as exc:
            logger.error("Gmail initial sync failed: %s", exc)

    async def _poll_once(self) -> None:
        """Poll for new messages since last history ID."""
        if not self._history_id:
            await self._initial_sync()
            return

        loop = asyncio.get_running_loop()

        try:
            history_response = await loop.run_in_executor(
                None,
                lambda: self._service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=self._history_id,
                    historyTypes=["messageAdded"],
                )
                .execute(),
            )

            self._history_id = history_response.get("historyId", self._history_id)
            histories = history_response.get("history", [])

            message_ids: set[str] = set()
            for history in histories:
                for msg_added in history.get("messagesAdded", []):
                    msg_id = msg_added["message"]["id"]
                    message_ids.add(msg_id)

            for msg_id in message_ids:
                await self._process_message(msg_id)

        except Exception as exc:
            logger.error("Gmail poll_once error: %s", exc)
            # Reset history ID on errors to re-sync
            self._history_id = None

    async def _process_message(self, message_id: str) -> None:
        """Fetch a message and check against provider patterns and directives."""
        loop = asyncio.get_running_loop()

        try:
            msg = await loop.run_in_executor(
                None,
                lambda: self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute(),
            )

            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            snippet = msg.get("snippet", "")
            body = self._extract_body(msg.get("payload", {}))

            email_msg = EmailMessage(
                message_id=message_id,
                sender=sender,
                subject=subject,
                body=body,
                snippet=snippet,
            )

            # Check against known provider patterns (fast path)
            matched_provider = await self._check_provider_patterns(email_msg)
            if matched_provider and self._on_bill_email:
                await self._on_bill_email(
                    matched_provider.slug,
                    message_id,
                    subject,
                    body,
                    snippet,
                )

            # Check against active user directive watch patterns
            matched_directives = await self._check_directive_matches(email_msg)
            if matched_directives and self._on_directive_match:
                for directive in matched_directives:
                    await self._on_directive_match(
                        directive.id,
                        subject,
                        snippet,
                    )

        except Exception as exc:
            logger.error("Error processing message %s: %s", message_id, exc)

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from Gmail message payload."""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get(
            "data"
        ):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )

        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get(
                "data"
            ):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
            # Recurse into multipart
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        # Fallback: try HTML parts
        for part in parts:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                from bs4 import BeautifulSoup

                html = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
                soup = BeautifulSoup(html, "html.parser")
                return soup.get_text(separator="\n", strip=True)

        return ""

    async def _check_provider_patterns(self, message: EmailMessage) -> Provider | None:
        """
        Check email sender against known provider email_sender_patterns.
        Returns the matching provider or None.
        """
        session = await get_session()
        try:
            stmt = select(Provider).where(Provider.is_active == True)  # noqa: E712
            result = await session.execute(stmt)
            providers = result.scalars().all()

            _, sender_email = parseaddr(message.sender)
            sender_email = sender_email.lower()

            for provider in providers:
                if not provider.email_sender_pattern:
                    continue
                try:
                    if re.search(
                        provider.email_sender_pattern, sender_email, re.IGNORECASE
                    ):
                        logger.info(
                            "Email from %s matched provider %s",
                            sender_email,
                            provider.slug,
                        )
                        return provider
                except re.error:
                    logger.warning(
                        "Invalid regex for provider %s: %s",
                        provider.slug,
                        provider.email_sender_pattern,
                    )

            return None
        finally:
            await session.close()

    async def _check_directive_matches(
        self, message: EmailMessage
    ) -> list[UserDirective]:
        """
        Load all active watch_email directives from DB.
        Check sender and subject against each directive's parameters.
        Returns matching directives (may be multiple).
        No LLM call — pure pattern matching.
        """
        session = await get_session()
        try:
            stmt = select(UserDirective).where(
                UserDirective.status == "active",
                UserDirective.directive_type == "watch_email",
            )
            result = await session.execute(stmt)
            directives = result.scalars().all()

            matches: list[UserDirective] = []
            _, sender_email = parseaddr(message.sender)
            sender_lower = sender_email.lower()
            subject_lower = message.subject.lower()

            for directive in directives:
                try:
                    params = json.loads(directive.parameters_json)
                except (json.JSONDecodeError, TypeError):
                    continue

                sender_pattern = params.get("sender_pattern", "")
                subject_keywords = params.get("subject_keywords", [])

                sender_match = False
                if sender_pattern:
                    try:
                        sender_match = bool(
                            re.search(sender_pattern, sender_lower, re.IGNORECASE)
                        )
                    except re.error:
                        sender_match = sender_pattern.lower() in sender_lower

                keyword_match = False
                if subject_keywords:
                    keyword_match = any(
                        kw.lower() in subject_lower for kw in subject_keywords
                    )

                # Match if sender matches AND (keywords match or no keywords specified)
                if sender_match and (keyword_match or not subject_keywords):
                    matches.append(directive)
                # Also match if no sender pattern but keywords match
                elif not sender_pattern and keyword_match:
                    matches.append(directive)

            return matches
        finally:
            await session.close()
