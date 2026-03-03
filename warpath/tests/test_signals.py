"""Tests for individual signal scorers — golden test vectors."""

from __future__ import annotations

import numpy as np
import pytest

from warpath.data.candle_builder import Candle
from warpath.data.indicators import (
    compute_atr,
    compute_bollinger,
    compute_bb_bandwidth,
    compute_heikin_ashi,
    compute_parabolic_sar,
)
from warpath.signals.bollinger import score_bollinger
from warpath.signals.dual_thrust import score_dual_thrust
from warpath.signals.heikin_ashi import score_heikin_ashi
from warpath.signals.parabolic_sar import score_parabolic_sar


class TestBollingerScorer:
    """Bollinger Bands signal scorer tests."""

    def test_score_range_negative_one_to_positive_one(self, sample_candles):
        upper, mid, lower = compute_bollinger(sample_candles)
        bw = compute_bb_bandwidth(upper, lower, mid)
        score = score_bollinger(sample_candles, upper, mid, lower, bw)
        assert -1.0 <= score <= 1.0

    def test_uptrend_positive_score(self, sample_candles):
        """Uptrending candles should produce positive BB score."""
        upper, mid, lower = compute_bollinger(sample_candles)
        bw = compute_bb_bandwidth(upper, lower, mid)
        score = score_bollinger(sample_candles, upper, mid, lower, bw)
        assert score > 0, f"Expected positive score for uptrend, got {score}"

    def test_downtrend_negative_score(self, downtrend_candles):
        """Downtrending candles should produce negative BB score."""
        upper, mid, lower = compute_bollinger(downtrend_candles)
        bw = compute_bb_bandwidth(upper, lower, mid)
        score = score_bollinger(downtrend_candles, upper, mid, lower, bw)
        assert score < 0, f"Expected negative score for downtrend, got {score}"

    def test_insufficient_candles_returns_zero(self):
        """Fewer than 5 candles should return 0."""
        candles = [Candle(0, 100, 101, 99, 100)] * 3
        upper = np.array([np.nan] * 3)
        mid = np.array([np.nan] * 3)
        lower = np.array([np.nan] * 3)
        bw = np.array([np.nan] * 3)
        assert score_bollinger(candles, upper, mid, lower, bw) == 0.0

    def test_price_above_upper_band_positive(self, sample_candles):
        """Price above upper band should add positive score."""
        upper, mid, lower = compute_bollinger(sample_candles)
        bw = compute_bb_bandwidth(upper, lower, mid)
        # Manipulate last candle to be above upper band
        sample_candles[-1] = Candle(
            sample_candles[-1].timestamp,
            upper[-1] + 1, upper[-1] + 2, upper[-1] + 0.5, upper[-1] + 1.5,
            timeframe="5m", closed=True,
        )
        score = score_bollinger(sample_candles, upper, mid, lower, bw)
        assert score > 0


class TestParabolicSARScorer:
    """Parabolic SAR signal scorer tests."""

    def test_score_range(self, sample_candles):
        sar = compute_parabolic_sar(sample_candles)
        atr = compute_atr(sample_candles)
        score = score_parabolic_sar(sample_candles, sar, atr)
        assert -1.0 <= score <= 1.0

    def test_uptrend_positive(self, sample_candles):
        """SAR below price in uptrend should give positive score."""
        sar = compute_parabolic_sar(sample_candles)
        atr = compute_atr(sample_candles)
        score = score_parabolic_sar(sample_candles, sar, atr)
        assert score > 0, f"Expected positive SAR score in uptrend, got {score}"

    def test_downtrend_negative(self, downtrend_candles):
        """SAR above price in downtrend should give negative score."""
        sar = compute_parabolic_sar(downtrend_candles)
        atr = compute_atr(downtrend_candles)
        score = score_parabolic_sar(downtrend_candles, sar, atr)
        assert score < 0, f"Expected negative SAR score in downtrend, got {score}"

    def test_insufficient_candles(self):
        """Fewer than 3 candles returns 0."""
        candles = [Candle(0, 100, 101, 99, 100)]
        sar = np.array([np.nan])
        atr = np.array([np.nan])
        assert score_parabolic_sar(candles, sar, atr) == 0.0


class TestHeikinAshiScorer:
    """Heikin-Ashi signal scorer tests."""

    def test_score_range(self, sample_candles):
        ha = compute_heikin_ashi(sample_candles)
        score = score_heikin_ashi(ha)
        assert -1.0 <= score <= 1.0

    def test_green_streak_positive(self, sample_candles):
        """Uptrend HA candles should produce positive score."""
        ha = compute_heikin_ashi(sample_candles)
        score = score_heikin_ashi(ha)
        assert score > 0

    def test_red_streak_negative(self, downtrend_candles):
        """Downtrend HA candles should produce negative score."""
        ha = compute_heikin_ashi(downtrend_candles)
        score = score_heikin_ashi(ha)
        assert score < 0

    def test_insufficient_candles(self):
        assert score_heikin_ashi([]) == 0.0
        assert score_heikin_ashi([Candle(0, 1, 1, 1, 1)]) == 0.0


class TestDualThrustScorer:
    """Dual Thrust signal scorer tests."""

    def test_score_range(self, sample_candles):
        score = score_dual_thrust(sample_candles)
        assert -1.0 <= score <= 1.0

    def test_breakout_up_positive(self, sample_candles):
        """Price breaking above upper trigger should give positive score."""
        score = score_dual_thrust(sample_candles)
        # With an uptrend, should have positive bias
        assert score >= 0

    def test_breakout_down_negative(self, downtrend_candles):
        """Price breaking below lower trigger should give negative score."""
        score = score_dual_thrust(downtrend_candles)
        assert score <= 0

    def test_insufficient_candles(self):
        candles = [Candle(0, 100, 101, 99, 100)] * 3
        assert score_dual_thrust(candles) == 0.0
