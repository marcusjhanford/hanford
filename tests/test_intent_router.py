"""Tests for the intent router module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hanford.config import Config
from hanford.intent.router import IntentResult, IntentRouter, IntentType
from hanford.llm import LLMResponse
from hanford.models.pending_action import PendingAction


class TestIntentRouterFastPath:
    """Tests for fast-path heuristic classification (no LLM)."""

    @pytest.fixture
    def config(self):
        return Config(
            openai_api_key="test-key",
            openai_model="gpt-4o-mini",
        )

    @pytest.fixture
    def router(self, config):
        return IntentRouter(config)

    @pytest.fixture
    def pending_actions(self):
        """A list with one pending action for context."""
        action = MagicMock(spec=PendingAction)
        action.id = 1
        action.status = "awaiting_approval"
        return [action]

    # --- Approve ---

    @pytest.mark.asyncio
    async def test_approve_yes(self, router, pending_actions):
        result = await router.route("yes", pending_actions)
        assert result.intent == IntentType.APPROVE
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_approve_y(self, router, pending_actions):
        result = await router.route("y", pending_actions)
        assert result.intent == IntentType.APPROVE

    @pytest.mark.asyncio
    async def test_approve_go_ahead(self, router, pending_actions):
        result = await router.route("go ahead", pending_actions)
        assert result.intent == IntentType.APPROVE

    @pytest.mark.asyncio
    async def test_approve_1(self, router, pending_actions):
        result = await router.route("1", pending_actions)
        assert result.intent == IntentType.APPROVE

    @pytest.mark.asyncio
    async def test_approve_without_pending_goes_to_llm(self, router):
        """'yes' without pending actions should not fast-path to APPROVE."""
        resp = LLMResponse(
            content='{"intent": "UNKNOWN", "confidence": 0.5, "extracted": ""}',
            model="gpt-4o-mini",
            provider="openai",
        )

        with patch.object(
            router._client, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await router.route("yes", [])
            # Without pending actions, APPROVE intent from LLM gets remapped to UNKNOWN
            assert result.intent == IntentType.UNKNOWN

    # --- Reject ---

    @pytest.mark.asyncio
    async def test_reject_no(self, router, pending_actions):
        result = await router.route("no", pending_actions)
        assert result.intent == IntentType.REJECT
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_reject_n(self, router, pending_actions):
        result = await router.route("n", pending_actions)
        assert result.intent == IntentType.REJECT

    @pytest.mark.asyncio
    async def test_reject_2(self, router, pending_actions):
        result = await router.route("2", pending_actions)
        assert result.intent == IntentType.REJECT

    # --- Switch to Telegram ---

    @pytest.mark.asyncio
    async def test_switch_to_telegram(self, router):
        result = await router.route("switch to telegram", None)
        assert result.intent == IntentType.SWITCH_TO_MESSAGING
        assert result.channel_target == "telegram"

    @pytest.mark.asyncio
    async def test_switch_to_telegram_variant(self, router):
        result = await router.route("message me on telegram", None)
        assert result.intent == IntentType.SWITCH_TO_MESSAGING
        assert result.channel_target == "telegram"

    # --- Switch to WhatsApp ---

    @pytest.mark.asyncio
    async def test_switch_to_whatsapp(self, router):
        result = await router.route("switch to whatsapp", None)
        assert result.intent == IntentType.SWITCH_TO_MESSAGING
        assert result.channel_target == "whatsapp"

    # --- Switch to TUI ---

    @pytest.mark.asyncio
    async def test_switch_to_tui(self, router):
        result = await router.route("switch back to device", None)
        assert result.intent == IntentType.SWITCH_TO_TUI

    @pytest.mark.asyncio
    async def test_switch_back_to_terminal(self, router):
        result = await router.route("back to terminal", None)
        assert result.intent == IntentType.SWITCH_TO_TUI

    # --- Status request ---

    @pytest.mark.asyncio
    async def test_status_request(self, router):
        result = await router.route("status", None)
        assert result.intent == IntentType.STATUS_REQUEST

    @pytest.mark.asyncio
    async def test_status_whats_happening(self, router):
        result = await router.route("what's happening", None)
        assert result.intent == IntentType.STATUS_REQUEST

    # --- Generic text mode ---

    @pytest.mark.asyncio
    async def test_switch_to_text_mode(self, router):
        result = await router.route("switch to text mode", None)
        assert result.intent == IntentType.SWITCH_TO_MESSAGING
        assert result.channel_target == "telegram"  # Default


class TestIntentRouterLLM:
    """Tests for LLM-based classification."""

    @pytest.fixture
    def config(self):
        return Config(openai_api_key="test-key", openai_model="gpt-4o-mini")

    @pytest.fixture
    def router(self, config):
        return IntentRouter(config)

    @pytest.mark.asyncio
    async def test_llm_classification_new_directive(self, router):
        """Test that complex messages go to LLM classification."""
        resp = LLMResponse(
            content='{"intent": "NEW_DIRECTIVE", "confidence": 0.95, "extracted": "watch for United Airlines confirmation"}',
            model="gpt-4o-mini",
            provider="openai",
        )

        with patch.object(
            router._client, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await router.route(
                "keep an eye out for a confirmation from United Airlines",
                None,
            )

        assert result.intent == IntentType.NEW_DIRECTIVE
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_llm_error_returns_unknown(self, router):
        """Test that LLM errors result in UNKNOWN intent."""
        with patch.object(
            router._client,
            "chat_completion",
            new_callable=AsyncMock,
            side_effect=Exception("API down"),
        ):
            result = await router.route(
                "something that needs LLM classification",
                None,
            )

        assert result.intent == IntentType.UNKNOWN
        assert result.confidence == 0.0
