"""Tests for the unified LLM client abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hanford.config import Config
from hanford.llm import LLMClient, LLMMessage, LLMResponse, strip_code_fences


class TestStripCodeFences:
    """Tests for the strip_code_fences helper."""

    def test_no_fences(self):
        assert strip_code_fences('{"key": "value"}') == '{"key": "value"}'

    def test_json_fences(self):
        assert strip_code_fences('```json\n{"key": "value"}\n```') == '{"key": "value"}'

    def test_plain_fences(self):
        assert strip_code_fences('```\n{"key": "value"}\n```') == '{"key": "value"}'

    def test_whitespace(self):
        assert strip_code_fences('  \n```json\n{"a":1}\n```  \n') == '{"a":1}'

    def test_empty(self):
        assert strip_code_fences("") == ""


class TestLLMClientOpenAI:
    """Tests for OpenAI provider path."""

    @pytest.fixture
    def config(self):
        return Config(
            llm_provider="openai",
            openai_api_key="test-key",
            openai_base_url="https://api.openai.com/v1",
            openai_model="gpt-4o-mini",
        )

    @pytest.fixture
    def client(self, config):
        return LLMClient(config)

    def test_provider_is_openai(self, client):
        assert client._provider == "openai"

    def test_model_returns_openai_model(self, client):
        assert client.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_chat_completion_openai(self, client):
        """Test that OpenAI provider calls the OpenAI SDK."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        with patch.object(
            client._openai_client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await client.chat_completion(
                messages=[LLMMessage(role="user", content="Hi")],
                temperature=0.0,
                max_tokens=100,
            )

        assert result.content == "Hello!"
        assert result.provider == "openai"
        assert result.usage["input_tokens"] == 10
        assert result.usage["output_tokens"] == 5


class TestLLMClientAnthropic:
    """Tests for Anthropic provider path."""

    @pytest.fixture
    def config(self):
        return Config(
            llm_provider="anthropic",
            anthropic_api_key="test-ant-key",
            anthropic_model="claude-sonnet-4-20250514",
        )

    @pytest.fixture
    def client(self, config):
        with patch("anthropic.AsyncAnthropic", create=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            client = LLMClient(config)
            client._anthropic_client = mock_cls.return_value
            return client

    def test_provider_is_anthropic(self, client):
        assert client._provider == "anthropic"

    def test_model_returns_anthropic_model(self, client):
        assert client.model == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_chat_completion_anthropic(self, client):
        """Test that Anthropic provider calls the Anthropic SDK."""
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "Hello from Claude!"

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage = MagicMock(input_tokens=12, output_tokens=8)

        client._anthropic_client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.chat_completion(
            messages=[
                LLMMessage(role="system", content="You are helpful."),
                LLMMessage(role="user", content="Hi"),
            ],
            temperature=0.5,
            max_tokens=200,
        )

        assert result.content == "Hello from Claude!"
        assert result.provider == "anthropic"
        assert result.usage["input_tokens"] == 12
        assert result.usage["output_tokens"] == 8

        # Verify system prompt was separated correctly
        call_kwargs = client._anthropic_client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "You are helpful."
        # Messages should only contain user message, not system
        api_messages = call_kwargs.kwargs["messages"]
        assert len(api_messages) == 1
        assert api_messages[0]["role"] == "user"


class TestLLMClientProviderSelection:
    """Tests for provider selection logic."""

    def test_defaults_to_openai(self):
        config = Config(openai_api_key="k")
        client = LLMClient(config)
        assert client._provider == "openai"
        assert client._openai_client is not None

    def test_explicit_openai(self):
        config = Config(llm_provider="openai", openai_api_key="k")
        client = LLMClient(config)
        assert client._provider == "openai"

    def test_anthropic_selection(self):
        with patch("anthropic.AsyncAnthropic", create=True):
            config = Config(llm_provider="anthropic", anthropic_api_key="k")
            client = LLMClient(config)
            assert client._provider == "anthropic"


class TestLLMClientLocalProviders:
    """Tests for local LLM providers (Ollama and vLLM)."""

    @pytest.fixture
    def ollama_config(self):
        return Config(
            llm_provider="ollama",
            ollama_base_url="http://localhost:11434/v1",
            ollama_model="llama3.2",
        )

    @pytest.fixture
    def ollama_client(self, ollama_config):
        return LLMClient(ollama_config)

    @pytest.fixture
    def vllm_config(self):
        return Config(
            llm_provider="vllm",
            vllm_base_url="http://localhost:8000/v1",
            vllm_model="meta-llama/Llama-2-7b-chat-hf",
            vllm_api_key="test-key",
        )

    @pytest.fixture
    def vllm_client(self, vllm_config):
        return LLMClient(vllm_config)

    def test_ollama_provider(self, ollama_client):
        assert ollama_client._provider == "ollama"
        assert ollama_client._openai_client is not None

    def test_ollama_model(self, ollama_client):
        assert ollama_client.model == "llama3.2"

    def test_vllm_provider(self, vllm_client):
        assert vllm_client._provider == "vllm"
        assert vllm_client._openai_client is not None

    def test_vllm_model(self, vllm_client):
        assert vllm_client.model == "meta-llama/Llama-2-7b-chat-hf"

    def test_vllm_model_fallback(self):
        """Test vLLM with empty model uses fallback."""
        config = Config(llm_provider="vllm", vllm_base_url="http://localhost:8000/v1")
        client = LLMClient(config)
        assert client.model == "local-model"

    @pytest.mark.asyncio
    async def test_ollama_chat_completion(self, ollama_client):
        """Test that Ollama provider calls the OpenAI-compatible API."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Hello from Ollama!"))
        ]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        with patch.object(
            ollama_client._openai_client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await ollama_client.chat_completion(
                messages=[LLMMessage(role="user", content="Hi")],
                temperature=0.0,
                max_tokens=100,
            )

        assert result.content == "Hello from Ollama!"
        assert result.provider == "ollama"
        assert result.model == "llama3.2"
        assert result.usage["input_tokens"] == 10
        assert result.usage["output_tokens"] == 5

    @pytest.mark.asyncio
    async def test_vllm_chat_completion(self, vllm_client):
        """Test that vLLM provider calls the OpenAI-compatible API."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Hello from vLLM!"))
        ]
        mock_response.usage = MagicMock(prompt_tokens=12, completion_tokens=8)

        with patch.object(
            vllm_client._openai_client.chat.completions,
            "create",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await vllm_client.chat_completion(
                messages=[LLMMessage(role="user", content="Hi")],
                temperature=0.5,
                max_tokens=200,
            )

        assert result.content == "Hello from vLLM!"
        assert result.provider == "vllm"
        assert result.model == "meta-llama/Llama-2-7b-chat-hf"
        assert result.usage["input_tokens"] == 12
        assert result.usage["output_tokens"] == 8
