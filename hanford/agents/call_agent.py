"""Call agent: dispatches outbound AI phone calls via Vapi.ai."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import requests
import yaml

from hanford.agents.base_agent import AgentResult, BaseAgent
from hanford.config import Config
from hanford.llm import LLMClient, LLMMessage, strip_code_fences

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"

OUTCOME_PARSE_PROMPT = """Analyze this phone call transcript and extract the outcome.

Return a JSON object with:
- "outcome": one of "success", "failure", "escalation_needed", "no_answer"
- "summary": a 1-2 sentence plain English summary of what happened
- "amount_saved": float if a discount/credit was negotiated, null otherwise
- "new_rate": float if a new monthly rate was agreed, null otherwise

Transcript:
{transcript}

Context:
The caller was negotiating on behalf of {user_name} with {provider_name}.
The target was to reduce the bill from ${current_amount} back toward ${baseline_amount}/mo.

Return only valid JSON.
"""


class CallAgent(BaseAgent):
    """
    Builds Vapi payload from provider YAML + negotiation script.
    Dispatches call. Polls for outcome. Parses transcript.
    Updates Interaction record.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._knowledge_dir = Path(__file__).resolve().parent.parent / "knowledge"
        self._llm = LLMClient(config)

    @property
    def agent_type(self) -> str:
        return "call"

    async def execute(
        self,
        provider_slug: str,
        context: dict[str, Any],
    ) -> AgentResult:
        """
        Execute an outbound AI phone call to the provider.

        Args:
            provider_slug: Matches knowledge/providers/*.yaml
            context: Must include 'phone_number', 'current_amount', 'baseline_amount',
                     'provider_name', 'user_name', 'account_identifier' (optional)
        """
        provider_profile = self._load_provider_profile(provider_slug)
        script = self._load_negotiation_script(
            provider_profile.get("category", "telecom")
        )

        phone_number = context.get("phone_number") or provider_profile.get(
            "phone_number", ""
        )
        if not phone_number:
            return AgentResult(
                success=False,
                outcome="failure",
                outcome_summary="No phone number available for this provider.",
                external_id="",
            )

        # Build the Vapi call payload
        system_prompt = self._build_system_prompt(
            provider_profile=provider_profile,
            script=script,
            context=context,
        )

        payload = {
            "phoneNumberId": self._config.vapi_phone_number_id,
            "customer": {
                "number": phone_number,
            },
            "assistant": {
                "model": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                    ],
                    "temperature": 0.7,
                },
                "voice": {
                    "provider": "11labs",
                    "voiceId": "21m00Tcm4TlvDq8ikWAM",  # Default Rachel voice
                },
                "firstMessage": self._build_first_message(context, provider_profile),
                "endCallMessage": "Thank you for your time. Goodbye.",
                "maxDurationSeconds": 2400,  # 40 minutes max
                "silenceTimeoutSeconds": 30,
                "name": f"Hanford - {context.get('provider_name', provider_slug)} negotiation",
            },
        }

        # Add IVR navigation hints if available
        ivr_map = provider_profile.get("ivr_navigation")
        if ivr_map:
            ivr_instructions = "\n".join(
                f"- When prompted '{step.get('prompt', '')}', press {step.get('key', '')}"
                for step in ivr_map
            )
            payload["assistant"]["model"]["messages"][0]["content"] += (
                f"\n\nIVR NAVIGATION:\n{ivr_instructions}"
            )

        # Dispatch the call
        call_id = await self._dispatch_call(payload)
        if not call_id:
            return AgentResult(
                success=False,
                outcome="failure",
                outcome_summary="Failed to initiate Vapi call.",
                external_id="",
            )

        logger.info("Vapi call dispatched: %s", call_id)

        # Poll for outcome
        result = await self._poll_for_outcome(call_id, context)
        return result

    async def check_status(self, external_id: str) -> AgentResult | None:
        """Check the status of an in-progress Vapi call."""
        call_data = await self._get_call(external_id)
        if not call_data:
            return None

        status = call_data.get("status", "")
        if status in ("queued", "ringing", "in-progress"):
            return None  # Still in progress

        return await self._parse_call_result(call_data, {})

    def _load_provider_profile(self, slug: str) -> dict[str, Any]:
        """Load provider YAML profile from knowledge base."""
        yaml_path = self._knowledge_dir / "providers" / f"{slug}.yaml"
        if not yaml_path.exists():
            logger.warning("Provider profile not found: %s", yaml_path)
            return {"name": slug, "category": "telecom"}

        with open(yaml_path) as f:
            return yaml.safe_load(f) or {}

    def _load_negotiation_script(self, category: str) -> str:
        """Load the negotiation script for the provider's category."""
        script_map = {
            "telecom": "telecom_dispute.md",
            "utility": "utility_dispute.md",
            "insurance": "insurance_billing.md",
            "healthcare": "insurance_billing.md",
        }
        script_file = script_map.get(category, "telecom_dispute.md")
        script_path = self._knowledge_dir / "scripts" / script_file

        if not script_path.exists():
            logger.warning("Negotiation script not found: %s", script_path)
            return "Negotiate politely but firmly for a reduction in the bill amount."

        return script_path.read_text()

    def _build_system_prompt(
        self,
        provider_profile: dict[str, Any],
        script: str,
        context: dict[str, Any],
    ) -> str:
        """Build the system prompt for the Vapi call assistant."""
        user_name = context.get("user_name", self._config.user_name)
        provider_name = context.get(
            "provider_name", provider_profile.get("name", "the provider")
        )
        current_amount = context.get("current_amount", 0)
        baseline_amount = context.get("baseline_amount", 0)
        account_id = context.get("account_identifier", "")

        account_line = f"Account identifier: {account_id}\n" if account_id else ""

        return f"""You are a helpful assistant calling {provider_name} customer service on behalf of {user_name}.

YOUR OBJECTIVE:
Negotiate the monthly bill down from ${current_amount:.2f} to approximately ${baseline_amount:.2f}/month,
or secure a one-time credit for the overcharge.

CALLER IDENTITY:
You are calling on behalf of: {user_name}
{account_line}
PROVIDER: {provider_name}
Current bill: ${current_amount:.2f}
Target rate: ${baseline_amount:.2f}/month

NEGOTIATION STRATEGY:
{script}

BEHAVIORAL RULES:
- Be polite but firm. You are a loyal customer who noticed an unexpected increase.
- If asked for account verification, provide: {user_name}. If asked for account number: {account_id or "ask the representative to look it up by name"}.
- If the representative cannot help, politely ask to speak with their retention department.
- If offered a promotional rate, confirm the duration and any conditions.
- If no resolution is possible, thank them and end the call gracefully.
- NEVER agree to new services or upgrades. Only negotiate existing charges.
- Keep responses concise and natural-sounding.

PROVIDER-SPECIFIC NOTES:
{json.dumps(provider_profile.get("negotiation_tips", []), indent=2)}
"""

    def _build_first_message(
        self, context: dict[str, Any], profile: dict[str, Any]
    ) -> str:
        """Build the first message the AI speaks when the call connects."""
        user_name = context.get("user_name", self._config.user_name)
        provider_name = context.get("provider_name", profile.get("name", ""))
        return (
            f"Hi, I'm calling on behalf of {user_name} regarding their "
            f"{provider_name} account. I noticed a recent increase in the "
            f"monthly bill and I'd like to discuss options for getting it adjusted."
        )

    async def _dispatch_call(self, payload: dict[str, Any]) -> str | None:
        """Send POST /call to Vapi and return the call ID."""
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    f"{VAPI_BASE_URL}/call",
                    headers={
                        "Authorization": f"Bearer {self._config.vapi_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30,
                ),
            )

            if response.status_code in (200, 201):
                data = response.json()
                return data.get("id")
            else:
                logger.error(
                    "Vapi call dispatch failed: %s %s",
                    response.status_code,
                    response.text,
                )
                return None

        except Exception as exc:
            logger.error("Vapi call dispatch error: %s", exc)
            return None

    async def _get_call(self, call_id: str) -> dict[str, Any] | None:
        """Fetch call details from Vapi."""
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    f"{VAPI_BASE_URL}/call/{call_id}",
                    headers={"Authorization": f"Bearer {self._config.vapi_api_key}"},
                    timeout=30,
                ),
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as exc:
            logger.error("Vapi get call error: %s", exc)
            return None

    async def _poll_for_outcome(
        self,
        call_id: str,
        context: dict[str, Any],
        max_wait: int = 2700,  # 45 minutes
        poll_interval: int = 30,
    ) -> AgentResult:
        """Poll Vapi for call completion, then parse the outcome."""
        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            call_data = await self._get_call(call_id)
            if not call_data:
                continue

            status = call_data.get("status", "")
            if status in ("queued", "ringing", "in-progress"):
                logger.debug("Call %s still %s (%ds elapsed)", call_id, status, elapsed)
                continue

            return await self._parse_call_result(call_data, context)

        # Timed out
        return AgentResult(
            success=False,
            outcome="failure",
            outcome_summary=f"Call timed out after {max_wait // 60} minutes.",
            external_id=call_id,
        )

    async def _parse_call_result(
        self,
        call_data: dict[str, Any],
        context: dict[str, Any],
    ) -> AgentResult:
        """Parse the Vapi call result and use LLM to extract outcome from transcript."""
        call_id = call_data.get("id", "")
        status = call_data.get("status", "")
        transcript = call_data.get("transcript", "")
        messages = call_data.get("messages", [])

        # Build transcript from messages if not directly available
        if not transcript and messages:
            transcript_lines = []
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", msg.get("message", ""))
                if content:
                    transcript_lines.append(f"{role}: {content}")
            transcript = "\n".join(transcript_lines)

        if status == "failed" or not transcript:
            end_reason = call_data.get("endedReason", "unknown")
            if end_reason in ("no-answer", "busy"):
                return AgentResult(
                    success=False,
                    outcome="no_answer",
                    outcome_summary=f"Call ended: {end_reason}.",
                    transcript=transcript or None,
                    external_id=call_id,
                )
            return AgentResult(
                success=False,
                outcome="failure",
                outcome_summary=f"Call failed: {end_reason}.",
                transcript=transcript or None,
                external_id=call_id,
            )

        # Use LLM to parse the transcript for outcome details
        parsed = await self._parse_transcript(transcript, context)
        return AgentResult(
            success=parsed.get("outcome") == "success",
            outcome=parsed.get("outcome", "failure"),
            outcome_summary=parsed.get("summary", "Call completed."),
            transcript=transcript,
            amount_saved=parsed.get("amount_saved"),
            external_id=call_id,
            raw_data={"new_rate": parsed.get("new_rate")},
        )

    async def _parse_transcript(
        self,
        transcript: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Use LLM to extract structured outcome from call transcript."""
        prompt = OUTCOME_PARSE_PROMPT.format(
            transcript=transcript[:8000],
            user_name=context.get("user_name", self._config.user_name),
            provider_name=context.get("provider_name", "the provider"),
            current_amount=context.get("current_amount", 0),
            baseline_amount=context.get("baseline_amount", 0),
        )

        try:
            response = await self._llm.chat_completion(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a precise call outcome analyzer. Return only valid JSON.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=512,
            )

            raw = strip_code_fences(response.content)
            return json.loads(raw)

        except (json.JSONDecodeError, Exception) as exc:
            logger.error("Transcript parse error: %s", exc)
            return {
                "outcome": "failure",
                "summary": "Could not parse call outcome from transcript.",
                "amount_saved": None,
                "new_rate": None,
            }
