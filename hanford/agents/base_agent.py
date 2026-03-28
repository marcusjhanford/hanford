"""Abstract base for all action agents. Designed for v0.2 extensibility."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentResult:
    """Standardized result from any agent execution."""

    success: bool
    outcome: str  # success | failure | escalation_needed | no_answer
    outcome_summary: str
    transcript: str | None = None
    amount_saved: float | None = None
    external_id: str = ""  # e.g. vapi_call_id
    raw_data: dict[str, Any] | None = None


class BaseAgent(ABC):
    """
    Interface for action agents. All agents inherit this.

    Designed for v0.2 extensibility: adding a WebAgent or EmailAgent
    requires only implementing this interface and registering it with
    the orchestrator's agent dispatcher based on provider YAML
    `preferred_contact_method`.
    """

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Return the agent type identifier (e.g. 'call', 'email', 'web')."""
        ...

    @abstractmethod
    async def execute(
        self,
        provider_slug: str,
        context: dict[str, Any],
    ) -> AgentResult:
        """
        Execute the action against the provider.

        Args:
            provider_slug: Matches knowledge/providers/*.yaml
            context: All data needed for execution (from PendingAction.context_json)

        Returns:
            AgentResult with outcome details.
        """
        ...

    @abstractmethod
    async def check_status(self, external_id: str) -> AgentResult | None:
        """
        Check the status of an in-progress action.
        Returns None if the action is still in progress.
        """
        ...
