"""Tests for the anomaly detector module."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hanford.config import Config
from hanford.monitor.anomaly_detector import AnomalyDetector, AnomalyResult


class TestAnomalyDetector:
    """Tests for AnomalyDetector."""

    @pytest.fixture
    def config(self):
        return Config(anomaly_threshold=0.15)

    @pytest.fixture
    def detector(self, config):
        return AnomalyDetector(config)

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_anomaly_detected(self, detector, mock_session):
        """Test that a bill 30% above baseline is flagged as anomalous."""
        # Mock the rolling baseline query to return 3 bills at $65 each
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(65.0,), (65.0,), (65.0,)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await detector.analyze(
            session=mock_session,
            provider_id=1,
            current_amount=85.0,
            baseline_amount=65.0,
        )

        assert result.is_anomalous is True
        assert result.score > 0.15
        assert result.baseline_amount == 65.0
        assert "above" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_normal_bill(self, detector, mock_session):
        """Test that a bill within threshold is not flagged."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(65.0,), (66.0,), (64.0,)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await detector.analyze(
            session=mock_session,
            provider_id=1,
            current_amount=67.0,
            baseline_amount=65.0,
        )

        assert result.is_anomalous is False
        assert "within normal" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_exact_threshold(self, detector, mock_session):
        """Test behavior at exactly the threshold boundary."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(100.0,), (100.0,), (100.0,)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        # 15% above baseline = exactly at threshold
        result = await detector.analyze(
            session=mock_session,
            provider_id=1,
            current_amount=115.0,
            baseline_amount=100.0,
        )

        # At exactly 15%, deviation > threshold is False (not strictly greater)
        # Actually 15.0% > 15% threshold — this is at the boundary
        assert result.deviation_pct == pytest.approx(0.15, abs=0.01)

    @pytest.mark.asyncio
    async def test_fewer_than_three_bills_uses_fallback(self, detector, mock_session):
        """Test that fewer than 3 bills falls back to stored baseline."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(70.0,)]  # Only 1 bill
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await detector.analyze(
            session=mock_session,
            provider_id=1,
            current_amount=90.0,
            baseline_amount=65.0,  # Stored baseline
        )

        # Should use 65.0 as baseline (the fallback), not 70.0
        assert result.baseline_amount == 65.0
        assert result.is_anomalous is True

    @pytest.mark.asyncio
    async def test_zero_baseline(self, detector, mock_session):
        """Test that zero baseline returns non-anomalous."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await detector.analyze(
            session=mock_session,
            provider_id=1,
            current_amount=50.0,
            baseline_amount=0.0,
        )

        assert result.is_anomalous is False
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_score_clamped_to_one(self, detector, mock_session):
        """Test that score is clamped to 1.0 for huge deviations."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(50.0,), (50.0,), (50.0,)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await detector.analyze(
            session=mock_session,
            provider_id=1,
            current_amount=500.0,  # 900% deviation
            baseline_amount=50.0,
        )

        assert result.score == 1.0
        assert result.is_anomalous is True
