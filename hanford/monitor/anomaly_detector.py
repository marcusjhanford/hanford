"""Anomaly detection: compares current bill against rolling baseline."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hanford.config import Config
from hanford.models.bill import Bill

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    """Result of anomaly analysis on a bill."""

    score: float  # 0.0–1.0
    reason: str
    is_anomalous: bool
    baseline_amount: float
    deviation_pct: float


class AnomalyDetector:
    """
    Rolling 3-bill average baseline. Configurable threshold (default 15%).
    Returns anomaly score and human-readable reason string.
    """

    def __init__(self, config: Config) -> None:
        self._threshold = config.anomaly_threshold

    async def analyze(
        self,
        session: AsyncSession,
        provider_id: int,
        current_amount: float,
        baseline_amount: float,
    ) -> AnomalyResult:
        """
        Analyze a bill amount against the provider's baseline.

        Uses the rolling 3-bill average as the baseline. If fewer than 3 bills
        exist, uses the provider's stored baseline_amount. The anomaly score
        maps the deviation percentage onto a 0.0–1.0 scale.
        """
        rolling_baseline = await self._compute_rolling_baseline(
            session, provider_id, fallback=baseline_amount
        )

        if rolling_baseline <= 0:
            return AnomalyResult(
                score=0.0,
                reason="No baseline established yet.",
                is_anomalous=False,
                baseline_amount=0.0,
                deviation_pct=0.0,
            )

        deviation = current_amount - rolling_baseline
        deviation_pct = deviation / rolling_baseline

        # Score: map deviation percentage to 0–1 range
        # 0% deviation → 0.0 score, 100%+ deviation → 1.0 score
        score = min(max(abs(deviation_pct), 0.0), 1.0)

        is_anomalous = deviation_pct > self._threshold

        if is_anomalous:
            pct_display = round(deviation_pct * 100)
            reason = (
                f"${current_amount:.2f} is {pct_display}% above your usual "
                f"${rolling_baseline:.2f}."
            )
        else:
            reason = f"${current_amount:.2f} is within normal range of ${rolling_baseline:.2f}."

        return AnomalyResult(
            score=score,
            reason=reason,
            is_anomalous=is_anomalous,
            baseline_amount=rolling_baseline,
            deviation_pct=deviation_pct,
        )

    async def _compute_rolling_baseline(
        self,
        session: AsyncSession,
        provider_id: int,
        fallback: float,
    ) -> float:
        """
        Compute rolling 3-bill average for a provider.
        Falls back to the provider's stored baseline if < 3 historical bills exist.
        """
        stmt = (
            select(Bill.amount)
            .where(Bill.provider_id == provider_id)
            .order_by(Bill.parsed_at.desc())
            .limit(3)
        )
        result = await session.execute(stmt)
        amounts = [row[0] for row in result.fetchall()]

        if len(amounts) < 3:
            return (
                fallback
                if fallback > 0
                else (sum(amounts) / len(amounts) if amounts else 0.0)
            )

        return sum(amounts) / len(amounts)
