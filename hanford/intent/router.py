"""Intent router: classifies inbound messages, routes to handler."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hanford.config import Config
from hanford.llm import LLMClient, LLMMessage, strip_code_fences
from hanford.models.pending_action import PendingAction

logger = logging.getLogger(__name__)

INTENT_CLASSIFICATION_PROMPT = """Classify the following user message into exactly one intent.

Intents:
- APPROVE: user is approving a pending action (e.g. "yes", "do it", "go ahead", "y")
- REJECT: user is rejecting a pending action (e.g. "no", "cancel", "don't", "n")
- SWITCH_TO_MESSAGING: user wants to switch to WhatsApp or Telegram
  (e.g. "switch to text mode", "message me on telegram", "go to whatsapp")
- SWITCH_TO_TUI: user wants to switch back to terminal
  (e.g. "switch back to device", "back to terminal", "tui mode")
- NEW_DIRECTIVE: user is giving a new standing instruction
  (e.g. "watch for...", "keep an eye on...", "add X as a provider",
   "remind me when...", "track my...")
- STATUS_REQUEST: user asking for a summary of what's happening
  (e.g. "what are you doing?", "any updates?", "status")
- UNKNOWN: cannot classify

Message: "{message}"

Return JSON: {{"intent": "<INTENT>", "confidence": 0.0-1.0, "extracted": "<key info if any>"}}"""


class IntentType(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    SWITCH_TO_MESSAGING = "SWITCH_TO_MESSAGING"
    SWITCH_TO_TUI = "SWITCH_TO_TUI"
    NEW_DIRECTIVE = "NEW_DIRECTIVE"
    STATUS_REQUEST = "STATUS_REQUEST"
    UNKNOWN = "UNKNOWN"


@dataclass
class IntentResult:
    """Structured result of intent classification."""

    intent: IntentType
    confidence: float
    extracted: str = ""
    channel_target: str = ""  # Populated for SWITCH_TO_MESSAGING
    raw_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Fast-path heuristics (no LLM needed) ---

_APPROVE_EXACT = {
    "y",
    "yes",
    "yep",
    "yeah",
    "yup",
    "approve",
    "do it",
    "go ahead",
    "ok",
    "sure",
    "1",
}
_REJECT_EXACT = {"n", "no", "nope", "nah", "reject", "cancel", "dismiss", "don't", "2"}

_SWITCH_TO_TELEGRAM_PATTERNS = [
    "switch to telegram",
    "go to telegram",
    "message me on telegram",
    "use telegram",
    "telegram mode",
    "text me on telegram",
    "move to telegram",
]

_SWITCH_TO_WHATSAPP_PATTERNS = [
    "switch to whatsapp",
    "go to whatsapp",
    "message me on whatsapp",
    "use whatsapp",
    "whatsapp mode",
    "text me on whatsapp",
    "move to whatsapp",
]

_SWITCH_TO_MESSAGING_PATTERNS = [
    "switch to text mode",
    "switch to text",
    "text mode",
    "message me",
    "switch to messaging",
]

_SWITCH_TO_TUI_PATTERNS = [
    "switch back to device",
    "back to terminal",
    "tui mode",
    "switch to tui",
    "switch back to tui",
    "go back to terminal",
    "back to tui",
    "terminal mode",
    "device mode",
    "switch back",
]

_STATUS_PATTERNS = [
    "status",
    "what are you doing",
    "any updates",
    "what's happening",
    "whats happening",
    "update me",
    "what's going on",
    "whats going on",
    "what's new",
    "whats new",
]


class IntentRouter:
    """
    Every message a user sends — whether typed in the TUI input bar or sent
    via WhatsApp/Telegram — passes through the intent router. It classifies
    the message and returns a structured IntentResult that the orchestrator
    acts on.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = LLMClient(config)

    async def route(
        self,
        message: str,
        pending_actions: list[PendingAction] | None = None,
    ) -> IntentResult:
        """
        Classify a user message into an intent.

        Fast-path heuristics first (no LLM):
        - Single "y" or "yes" -> APPROVE (if pending actions exist)
        - Single "n" or "no" -> REJECT (if pending actions exist)
        - Exact phrase match on switch commands -> SWITCH_*

        LLM classification for everything else.
        """
        normalized = message.strip().lower()
        has_pending = bool(pending_actions)

        # --- Fast path: approve/reject ---
        if normalized in _APPROVE_EXACT and has_pending:
            return IntentResult(
                intent=IntentType.APPROVE,
                confidence=1.0,
                raw_message=message,
            )

        if normalized in _REJECT_EXACT and has_pending:
            return IntentResult(
                intent=IntentType.REJECT,
                confidence=1.0,
                raw_message=message,
            )

        # --- Fast path: switch to telegram ---
        for pattern in _SWITCH_TO_TELEGRAM_PATTERNS:
            if pattern in normalized:
                return IntentResult(
                    intent=IntentType.SWITCH_TO_MESSAGING,
                    confidence=1.0,
                    channel_target="telegram",
                    raw_message=message,
                )

        # --- Fast path: switch to whatsapp ---
        for pattern in _SWITCH_TO_WHATSAPP_PATTERNS:
            if pattern in normalized:
                return IntentResult(
                    intent=IntentType.SWITCH_TO_MESSAGING,
                    confidence=1.0,
                    channel_target="whatsapp",
                    raw_message=message,
                )

        # --- Fast path: generic switch to messaging (defaults to telegram) ---
        for pattern in _SWITCH_TO_MESSAGING_PATTERNS:
            if pattern in normalized:
                return IntentResult(
                    intent=IntentType.SWITCH_TO_MESSAGING,
                    confidence=0.9,
                    channel_target="telegram",  # Default
                    raw_message=message,
                )

        # --- Fast path: switch to TUI ---
        for pattern in _SWITCH_TO_TUI_PATTERNS:
            if pattern in normalized:
                return IntentResult(
                    intent=IntentType.SWITCH_TO_TUI,
                    confidence=1.0,
                    raw_message=message,
                )

        # --- Fast path: status request ---
        for pattern in _STATUS_PATTERNS:
            if pattern in normalized:
                return IntentResult(
                    intent=IntentType.STATUS_REQUEST,
                    confidence=1.0,
                    raw_message=message,
                )

        # --- LLM classification for everything else ---
        return await self._classify_with_llm(message, has_pending)

    async def _classify_with_llm(self, message: str, has_pending: bool) -> IntentResult:
        """Use LLM to classify a message that didn't match fast-path heuristics."""
        prompt = INTENT_CLASSIFICATION_PROMPT.format(message=message)

        try:
            response = await self._client.chat_completion(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a precise intent classifier. Return only valid JSON.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=256,
            )

            raw = strip_code_fences(response.content)
            data = json.loads(raw)
            intent_str = data.get("intent", "UNKNOWN").upper()
            confidence = float(data.get("confidence", 0.5))
            extracted = data.get("extracted", "")

            # Map to IntentType enum
            try:
                intent = IntentType(intent_str)
            except ValueError:
                intent = IntentType.UNKNOWN

            # Don't classify as APPROVE/REJECT if no pending actions
            if intent in (IntentType.APPROVE, IntentType.REJECT) and not has_pending:
                intent = IntentType.UNKNOWN

            # Extract channel target from SWITCH_TO_MESSAGING
            channel_target = ""
            if intent == IntentType.SWITCH_TO_MESSAGING:
                lower_extracted = (extracted or message).lower()
                if "whatsapp" in lower_extracted:
                    channel_target = "whatsapp"
                elif "telegram" in lower_extracted:
                    channel_target = "telegram"
                else:
                    channel_target = "telegram"  # Default

            return IntentResult(
                intent=intent,
                confidence=confidence,
                extracted=extracted,
                channel_target=channel_target,
                raw_message=message,
            )

        except json.JSONDecodeError as exc:
            logger.error("Intent router: invalid JSON from LLM: %s", exc)
            return IntentResult(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                raw_message=message,
            )
        except Exception as exc:
            logger.error("Intent router: LLM error: %s", exc)
            return IntentResult(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                raw_message=message,
            )
