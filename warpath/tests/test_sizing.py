"""Tests for position sizing — tiered allocation + regime coupling."""

from __future__ import annotations

import pytest

from warpath.config import Direction, GateResult, Regime
from warpath.risk.sizing import compute_effective_leverage, compute_size, select_tier


class TestTierSelection:
    """Tier selection from signal strength."""

    def test_strong_signal_tier_3(self):
        tier = select_tier(0.80)
        assert tier is not None
        assert tier.tier == 3

    def test_moderate_signal_tier_2(self):
        tier = select_tier(0.65)
        assert tier is not None
        assert tier.tier == 2

    def test_weak_signal_tier_1(self):
        tier = select_tier(0.50)
        assert tier is not None
        assert tier.tier == 1

    def test_below_threshold_none(self):
        tier = select_tier(0.30)
        assert tier is None

    def test_negative_signal_uses_abs(self):
        tier = select_tier(-0.80)
        assert tier is not None
        assert tier.tier == 3


class TestEffectiveLeverage:
    """Regime-coupled effective leverage."""

    def test_trend_full_leverage(self):
        lev = compute_effective_leverage(20.0, Regime.TREND)
        assert lev == 20.0

    def test_range_reduced_leverage(self):
        lev = compute_effective_leverage(20.0, Regime.RANGE)
        assert lev == 14.0  # 20 * 0.7

    def test_volatile_half_leverage(self):
        lev = compute_effective_leverage(20.0, Regime.VOLATILE)
        assert lev == 10.0  # 20 * 0.5, clamped to min 10

    def test_clamped_to_25(self):
        lev = compute_effective_leverage(30.0, Regime.TREND)
        assert lev == 25.0

    def test_clamped_to_10(self):
        lev = compute_effective_leverage(5.0, Regime.VOLATILE)
        assert lev == 10.0

    def test_caps_applied(self):
        lev = compute_effective_leverage(20.0, Regime.TREND, vol_cap=0.5)
        assert lev == 10.0


class TestComputeSize:
    """Full sizing computation."""

    def test_basic_sizing(self):
        result = compute_size(
            free_collateral=10.0,
            signal_strength=0.80,
            direction=Direction.LONG,
            regime=Regime.TREND,
        )
        assert result is not None
        assert result.tier == 3
        assert result.size_usd > 0
        assert result.direction == Direction.LONG

    def test_weak_signal_returns_none(self):
        result = compute_size(
            free_collateral=10.0,
            signal_strength=0.10,
            direction=Direction.LONG,
            regime=Regime.TREND,
        )
        assert result is None

    def test_vol_modifier_reduces_size(self):
        normal = compute_size(
            free_collateral=10.0,
            signal_strength=0.80,
            direction=Direction.LONG,
            regime=Regime.TREND,
        )
        reduced = compute_size(
            free_collateral=10.0,
            signal_strength=0.80,
            direction=Direction.LONG,
            regime=Regime.TREND,
            gate_result=GateResult(passed=True, sizing_modifier=0.5),
        )
        assert normal is not None and reduced is not None
        assert reduced.size_usd < normal.size_usd

    def test_zero_collateral_returns_none(self):
        result = compute_size(
            free_collateral=0.0,
            signal_strength=0.80,
            direction=Direction.LONG,
            regime=Regime.TREND,
        )
        assert result is None

    def test_size_respects_collateral_cap(self):
        result = compute_size(
            free_collateral=10.0,
            signal_strength=0.80,
            direction=Direction.LONG,
            regime=Regime.TREND,
        )
        assert result is not None
        # Should not exceed 25x * free_collateral
        assert result.size_usd <= 10.0 * 25.0

    def test_offset_bps_matches_tier(self):
        result = compute_size(
            free_collateral=10.0,
            signal_strength=0.80,
            direction=Direction.LONG,
            regime=Regime.TREND,
        )
        assert result is not None
        assert result.offset_bps == 5  # Tier 3 = 5bps
