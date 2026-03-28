"""Tests for the call agent module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hanford.agents.call_agent import CallAgent
from hanford.config import Config
from hanford.llm import LLMResponse


class TestCallAgent:
    """Tests for CallAgent."""

    @pytest.fixture
    def config(self):
        return Config(
            openai_api_key="test-key",
            vapi_api_key="test-vapi-key",
            vapi_phone_number_id="test-phone-id",
            user_name="Test User",
        )

    @pytest.fixture
    def agent(self, config):
        return CallAgent(config)

    def test_agent_type(self, agent):
        assert agent.agent_type == "call"

    def test_load_provider_profile_existing(self, agent):
        """Test loading an existing provider profile."""
        profile = agent._load_provider_profile("att")
        assert profile["name"] == "AT&T"
        assert profile["category"] == "telecom"
        assert profile["phone_number"] is not None

    def test_load_provider_profile_missing(self, agent):
        """Test loading a non-existent provider profile."""
        profile = agent._load_provider_profile("nonexistent")
        assert profile["name"] == "nonexistent"
        assert profile["category"] == "telecom"

    def test_load_negotiation_script_telecom(self, agent):
        """Test loading the telecom negotiation script."""
        script = agent._load_negotiation_script("telecom")
        assert (
            "Negotiate" in script or "negotiate" in script or "bill" in script.lower()
        )

    def test_load_negotiation_script_utility(self, agent):
        """Test loading the utility negotiation script."""
        script = agent._load_negotiation_script("utility")
        assert len(script) > 100  # Non-empty script

    def test_load_negotiation_script_unknown_category(self, agent):
        """Test fallback for unknown category."""
        script = agent._load_negotiation_script("unknown_category")
        # Should fall back to telecom script
        assert len(script) > 0

    def test_build_system_prompt(self, agent):
        """Test building the system prompt for a call."""
        profile = {
            "name": "AT&T",
            "category": "telecom",
            "negotiation_tips": ["Be polite"],
        }
        context = {
            "user_name": "Test User",
            "provider_name": "AT&T",
            "current_amount": 89.0,
            "baseline_amount": 65.0,
            "account_identifier": "ACC123",
        }

        prompt = agent._build_system_prompt(profile, "Some script", context)

        assert "Test User" in prompt
        assert "AT&T" in prompt
        assert "$89.00" in prompt
        assert "$65.00" in prompt
        assert "ACC123" in prompt

    def test_build_first_message(self, agent):
        """Test building the first message for the call."""
        context = {"user_name": "Test User", "provider_name": "AT&T"}
        profile = {"name": "AT&T"}

        msg = agent._build_first_message(context, profile)

        assert "Test User" in msg
        assert "AT&T" in msg
        assert "increase" in msg.lower() or "bill" in msg.lower()

    @pytest.mark.asyncio
    async def test_execute_no_phone_number(self, agent):
        """Test that execution fails gracefully when no phone number is available."""
        context = {
            "phone_number": "",
            "provider_name": "Unknown Provider",
            "current_amount": 100.0,
            "baseline_amount": 70.0,
            "user_name": "Test User",
        }

        result = await agent.execute("nonexistent", context)

        assert result.success is False
        assert result.outcome == "failure"
        assert "phone number" in result.outcome_summary.lower()

    @pytest.mark.asyncio
    async def test_dispatch_call_failure(self, agent):
        """Test handling of Vapi API failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch(
            "hanford.agents.call_agent.requests.post", return_value=mock_response
        ):
            call_id = await agent._dispatch_call({"test": "payload"})

        assert call_id is None

    @pytest.mark.asyncio
    async def test_parse_transcript_success(self, agent):
        """Test successful transcript parsing."""
        resp = LLMResponse(
            content='{"outcome": "success", "summary": "Negotiated $20 off.", "amount_saved": 20.0, "new_rate": 65.0}',
            model="gpt-4o-mini",
            provider="openai",
        )

        with patch.object(
            agent._llm, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await agent._parse_transcript(
                "Agent: Hi... Rep: OK we can lower it...",
                {
                    "user_name": "Test",
                    "provider_name": "AT&T",
                    "current_amount": 85,
                    "baseline_amount": 65,
                },
            )

        assert result["outcome"] == "success"
        assert result["amount_saved"] == 20.0
