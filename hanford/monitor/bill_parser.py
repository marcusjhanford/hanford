"""LLM-based structured extraction of bill data from email bodies."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from hanford.config import Config
from hanford.llm import LLMClient, LLMMessage, strip_code_fences

logger = logging.getLogger(__name__)

BILL_PARSE_PROMPT = """Extract billing information from this email body.
Return a JSON object with exactly these fields:
- "amount": float (total due, in dollars)
- "due_date": string (YYYY-MM-DD format, or null if not found)
- "billing_period_start": string (YYYY-MM-DD format, or null if not found)
- "billing_period_end": string (YYYY-MM-DD format, or null if not found)

If you cannot determine the amount due, return {"amount": null}.
Only return the JSON object, no additional text.

Email body:
{body}
"""


@dataclass
class ParsedBill:
    """Structured result from parsing a bill email."""

    amount: float
    due_date: date | None
    billing_period_start: date | None
    billing_period_end: date | None


class BillParser:
    """Parses bill emails using an LLM to extract structured billing data."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = LLMClient(config)

    async def parse(self, email_body: str) -> ParsedBill | None:
        """
        Parse a bill email body into structured billing data.

        Uses the configured LLM for extraction. Returns None if the amount
        cannot be determined from the email content.
        """
        prompt = BILL_PARSE_PROMPT.format(body=email_body[:4000])

        try:
            response = await self._client.chat_completion(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a precise bill data extractor. Return only valid JSON.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=256,
            )

            raw = strip_code_fences(response.content)
            data = json.loads(raw)

            amount = data.get("amount")
            if amount is None:
                logger.info("Bill parser: could not determine amount from email.")
                return None

            return ParsedBill(
                amount=float(amount),
                due_date=_parse_date(data.get("due_date")),
                billing_period_start=_parse_date(data.get("billing_period_start")),
                billing_period_end=_parse_date(data.get("billing_period_end")),
            )

        except json.JSONDecodeError as exc:
            logger.error("Bill parser: invalid JSON from LLM: %s", exc)
            return None
        except Exception as exc:
            logger.error("Bill parser: unexpected error: %s", exc)
            return None


def _parse_date(value: str | None) -> date | None:
    """Parse a YYYY-MM-DD string into a date, returning None on failure."""
    if not value or value == "null":
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None
