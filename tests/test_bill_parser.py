"""Tests for the bill parser module."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from hanford.config import Config
from hanford.llm import LLMResponse
from hanford.monitor.bill_parser import BillParser, ParsedBill, _parse_date


class TestParseDate:
    """Tests for the _parse_date helper."""

    def test_valid_date(self):
        assert _parse_date("2026-03-15") == date(2026, 3, 15)

    def test_null_string(self):
        assert _parse_date("null") is None

    def test_none_value(self):
        assert _parse_date(None) is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_invalid_format(self):
        assert _parse_date("March 15, 2026") is None

    def test_garbage_input(self):
        assert _parse_date("not-a-date") is None


class TestBillParser:
    """Tests for the BillParser class."""

    @pytest.fixture
    def config(self):
        return Config(
            openai_api_key="test-key",
            openai_base_url="https://api.openai.com/v1",
            openai_model="gpt-4o-mini",
        )

    @pytest.fixture
    def parser(self, config):
        return BillParser(config)

    def _mock_response(self, content: str) -> LLMResponse:
        return LLMResponse(content=content, model="gpt-4o-mini", provider="openai")

    @pytest.mark.asyncio
    async def test_parse_successful(self, parser):
        """Test successful parsing of a bill email."""
        resp = self._mock_response(
            '{"amount": 89.00, "due_date": "2026-03-18", "billing_period_start": "2026-02-01", "billing_period_end": "2026-02-28"}'
        )

        with patch.object(
            parser._client, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await parser.parse("Your AT&T bill of $89.00 is due March 18.")

        assert result is not None
        assert result.amount == 89.00
        assert result.due_date == date(2026, 3, 18)
        assert result.billing_period_start == date(2026, 2, 1)
        assert result.billing_period_end == date(2026, 2, 28)

    @pytest.mark.asyncio
    async def test_parse_null_amount(self, parser):
        """Test that null amount returns None."""
        resp = self._mock_response('{"amount": null}')

        with patch.object(
            parser._client, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await parser.parse("Some random email that isn't a bill.")

        assert result is None

    @pytest.mark.asyncio
    async def test_parse_json_with_code_fences(self, parser):
        """Test parsing when LLM wraps JSON in code fences."""
        resp = self._mock_response(
            '```json\n{"amount": 65.00, "due_date": "2026-04-01", "billing_period_start": null, "billing_period_end": null}\n```'
        )

        with patch.object(
            parser._client, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await parser.parse("Comcast bill: $65.00 due April 1.")

        assert result is not None
        assert result.amount == 65.00
        assert result.due_date == date(2026, 4, 1)
        assert result.billing_period_start is None

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self, parser):
        """Test handling of invalid JSON from LLM."""
        resp = self._mock_response("This is not JSON")

        with patch.object(
            parser._client, "chat_completion", new_callable=AsyncMock, return_value=resp
        ):
            result = await parser.parse("Some email body.")

        assert result is None

    @pytest.mark.asyncio
    async def test_parse_api_error(self, parser):
        """Test handling of API errors."""
        with patch.object(
            parser._client,
            "chat_completion",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            result = await parser.parse("Some email body.")

        assert result is None
