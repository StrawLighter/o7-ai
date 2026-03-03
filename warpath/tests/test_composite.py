"""Tests for composite scoring + regime adjustment + tier mapping."""

from __future__ import annotations

import pytest

from warpath.config import Direction, Regime
from warpath.signals.composite import CompositeScorer


class TestCompositeScorer:
    """Composite signal scoring tests."""

    def test_warmup_returns_neutral(self):
        """Insufficient candles should return neutral signal."""
        scorer = CompositeScorer()
        # Only 5 candles, need 25
        from warpath.data.candle_builder import Candle
        candles = [Candle(i, 100, 101, 99, 100, timeframe="5m", closed=True) for i in range(5)]
        signal = scorer.score(candles)
        assert signal.direction == Direction.NEUTRAL
        assert signal.tier == 0
        assert signal.composite_score == 0.0

    def test_uptrend_produces_long_signal(self, sample_candles):
        """Uptrending candles should produce LONG direction."""
        scorer = CompositeScorer()
        signal = scorer.score(sample_candles, oracle_price=167.0)
        assert signal.direction == Direction.LONG
        assert signal.composite_score > 0

    def test_downtrend_produces_short_signal(self, downtrend_candles):
        """Downtrending candles should produce SHORT direction."""
        scorer = CompositeScorer()
        signal = scorer.score(downtrend_candles, oracle_price=150.0)
        assert signal.direction == Direction.SHORT
        assert signal.composite_score < 0

    def test_score_bounded(self, sample_candles):
        """Composite score should be bounded."""
        scorer = CompositeScorer()
        signal = scorer.score(sample_candles)
        # Individual scores are [-1, 1], weights sum to 1.0
        assert -1.0 <= signal.composite_score <= 1.0

    def test_tier_mapping_thresholds(self, sample_candles):
        """Tier should map from composite score strength."""
        scorer = CompositeScorer()
        signal = scorer.score(sample_candles)
        # tier should be 0, 1, 2, or 3
        assert signal.tier in (0, 1, 2, 3)

    def test_signal_scores_populated(self, sample_candles):
        """Individual signal scores should be populated."""
        scorer = CompositeScorer()
        signal = scorer.score(sample_candles)
        # All sub-scores should be in range
        assert -1.0 <= signal.bb_score <= 1.0
        assert -1.0 <= signal.sar_score <= 1.0
        assert -1.0 <= signal.ha_score <= 1.0
        assert -1.0 <= signal.dt_score <= 1.0

    def test_atr_populated(self, sample_candles):
        """ATR should be non-zero for real candles."""
        scorer = CompositeScorer()
        signal = scorer.score(sample_candles)
        assert signal.atr > 0

    def test_regime_is_valid(self, sample_candles):
        """Regime should be a valid enum value."""
        scorer = CompositeScorer()
        signal = scorer.score(sample_candles)
        assert isinstance(signal.regime, Regime)

    def test_range_candles_produce_weak_signal(self, range_candles):
        """Range-bound candles should produce weak/neutral signal."""
        scorer = CompositeScorer()
        signal = scorer.score(range_candles)
        # Tight range should not produce strong signals
        assert abs(signal.composite_score) < 0.8
