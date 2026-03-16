"""Unified LLM client abstraction. Supports OpenAI and Anthropic (Claude) APIs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hanford.config import Config

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    """A single message in a chat conversation."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] | None = None


class LLMClient:
    """
    Unified async LLM client. Routes to OpenAI or Anthropic based on
    the LLM_PROVIDER config value.

    Usage:
        client = LLMClient(config)
        response = await client.chat_completion(
            messages=[
                LLMMessage(role="system", content="You are helpful."),
                LLMMessage(role="user", content="Hello"),
            ],
            temperature=0.0,
            max_tokens=256,
        )
        print(response.content)
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._provider = config.llm_provider
        self._openai_client: Any = None
        self._anthropic_client: Any = None

        if self._provider == "anthropic":
            self._init_anthropic()
        else:
            self._init_openai()

    def _init_openai(self) -> None:
        from openai import AsyncOpenAI

        self._openai_client = AsyncOpenAI(
            api_key=self._config.openai_api_key,
            base_url=self._config.openai_base_url,
        )

    def _init_anthropic(self) -> None:
        try:
            from anthropic import AsyncAnthropic

            self._anthropic_client = AsyncAnthropic(
                api_key=self._config.anthropic_api_key,
            )
        except ImportError:
            logger.error("anthropic package not installed. Run: pip install anthropic")
            raise

    @property
    def model(self) -> str:
        """Return the configured model name for the active provider."""
        if self._provider == "anthropic":
            return self._config.anthropic_model
        return self._config.openai_model

    async def chat_completion(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> LLMResponse:
        """
        Send a chat completion request to the configured LLM provider.

        Accepts a unified message format and returns a normalized response.
        Handles the differences between OpenAI and Anthropic APIs internally.
        """
        if self._provider == "anthropic":
            return await self._anthropic_completion(messages, temperature, max_tokens)
        return await self._openai_completion(messages, temperature, max_tokens)

    async def _openai_completion(
        self,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Send a completion request via the OpenAI API."""
        openai_messages = [{"role": m.role, "content": m.content} for m in messages]

        response = await self._openai_client.chat.completions.create(
            model=self._config.openai_model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }

        return LLMResponse(
            content=content,
            model=self._config.openai_model,
            provider="openai",
            usage=usage,
        )

    async def _anthropic_completion(
        self,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """
        Send a completion request via the Anthropic API.

        Anthropic's API separates the system prompt from the messages list,
        so we extract it here.
        """
        system_prompt = ""
        anthropic_messages: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                # Anthropic takes system as a top-level parameter, not a message
                system_prompt = msg.content
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": self._config.anthropic_model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._anthropic_client.messages.create(**kwargs)

        # Anthropic returns content as a list of content blocks
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        usage = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

        return LLMResponse(
            content=content,
            model=self._config.anthropic_model,
            provider="anthropic",
            usage=usage,
        )


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output. Common to both providers."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()
