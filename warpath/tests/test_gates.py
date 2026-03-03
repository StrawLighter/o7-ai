"""Tests for risk gate manager — each gate at exact threshold."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from warpath import config
from warpath.config import DegradedMode, Direction, GateID
from warpath.risk.gate_manager import GateManager


class TestGKill:
    """P0: Kill switch gate."""

    def test_kill_inactive_passes(self, mock_drift_wrapper):
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed

    def test_kill_active_blocks(self, mock_drift_wrapper):
        gm = GateManager()
        gm.activate_kill()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed
        assert result.failed_gate == GateID.G_KILL
        assert result.mode == DegradedMode.FULL_HALT

    def test_kill_deactivate_restores(self, mock_drift_wrapper):
        gm = GateManager()
        gm.activate_kill()
        gm.deactivate_kill()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed


class TestGLiq:
    """P1: Margin ratio with hysteresis (MG Patch 2)."""

    def test_above_clear_passes(self, mock_drift_wrapper):
        mock_drift_wrapper.get_margin_ratio.return_value = 3.0
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed

    def test_below_trigger_blocks(self, mock_drift_wrapper):
        mock_drift_wrapper.get_margin_ratio.return_value = 1.8
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed
        assert result.failed_gate == GateID.G_LIQ

    def test_hysteresis_holds_between(self, mock_drift_wrapper):
        """Between trigger (2.0) and clear (2.3): maintain current state."""
        gm = GateManager()

        # First: drop below trigger → activate
        mock_drift_wrapper.get_margin_ratio.return_value = 1.9
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed

        # Recovery to 2.1 — still within hysteresis band
        mock_drift_wrapper.get_margin_ratio.return_value = 2.1
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed  # Still blocked (hysteresis)

        # Recovery above 2.3 — clear
        mock_drift_wrapper.get_margin_ratio.return_value = 2.4
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed

    def test_hysteresis_clear_at_exactly_2_3(self, mock_drift_wrapper):
        gm = GateManager()
        mock_drift_wrapper.get_margin_ratio.return_value = 1.5
        gm.evaluate(mock_drift_wrapper, 155.0)  # Trigger

        mock_drift_wrapper.get_margin_ratio.return_value = 2.3
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed  # 2.3 is not > 2.3, stays latched

        mock_drift_wrapper.get_margin_ratio.return_value = 2.31
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed  # Now cleared


class TestGDD:
    """P2: Max drawdown from session peak."""

    def test_no_drawdown_passes(self, mock_drift_wrapper):
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0, current_nav=10.0)
        assert result.passed

    def test_drawdown_exceeds_threshold(self, mock_drift_wrapper):
        gm = GateManager()
        # Set HWM to 10.0
        gm.evaluate(mock_drift_wrapper, 155.0, current_nav=10.0)
        # Drop 20% → 8.0
        result = gm.evaluate(mock_drift_wrapper, 155.0, current_nav=8.0)
        assert not result.passed
        assert result.failed_gate == GateID.G_DD


class TestGDay:
    """P3: Daily loss limit."""

    def test_no_losses_passes(self, mock_drift_wrapper):
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0, current_nav=10.0)
        assert result.passed

    def test_daily_loss_blocks(self, mock_drift_wrapper):
        gm = GateManager()
        gm.state.daily_realized_pnl = -0.6  # -$0.60 on $10 = 6% > 5%
        result = gm.evaluate(mock_drift_wrapper, 155.0, current_nav=10.0)
        assert not result.passed
        assert result.failed_gate == GateID.G_DAY


class TestGConsec:
    """P4: Consecutive losses."""

    def test_no_losses_passes(self, mock_drift_wrapper):
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed

    def test_three_losses_blocks(self, mock_drift_wrapper):
        gm = GateManager()
        gm.state.consecutive_losses = 3
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed
        assert result.failed_gate == GateID.G_CONSEC

    def test_win_resets_counter(self, mock_drift_wrapper):
        gm = GateManager()
        gm.record_trade_result(-0.10, Direction.LONG, "sl")
        gm.record_trade_result(-0.10, Direction.LONG, "sl")
        assert gm.state.consecutive_losses == 2
        gm.record_trade_result(0.20, Direction.LONG, "tp")
        assert gm.state.consecutive_losses == 0


class TestGVol:
    """P5: Volatility spike."""

    def test_no_pause_passes(self, mock_drift_wrapper):
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed
        assert result.sizing_modifier == 1.0

    def test_vol_pause_returns_half_sizing(self, mock_drift_wrapper):
        gm = GateManager()
        gm.trigger_vol_pause()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed  # Passes but with modifier
        assert result.sizing_modifier == 0.5


class TestGFund:
    """P6: Funding rate gate (MG Patch 3)."""

    def test_favorable_funding_passes(self, mock_drift_wrapper):
        gm = GateManager()
        # LONG with negative funding = favorable
        result = gm.evaluate(
            mock_drift_wrapper, 155.0,
            funding_rate=-0.001, direction=Direction.LONG, tier=1,
        )
        assert result.passed

    def test_adverse_high_funding_blocks(self, mock_drift_wrapper):
        gm = GateManager()
        # LONG with very high positive funding = adverse
        result = gm.evaluate(
            mock_drift_wrapper, 155.0,
            funding_rate=0.003, direction=Direction.LONG, tier=1,
        )
        assert not result.passed
        assert result.failed_gate == GateID.G_FUND

    def test_moderate_adverse_requires_higher_tier(self, mock_drift_wrapper):
        gm = GateManager()
        # 0.10% funding requires Tier 3
        result = gm.evaluate(
            mock_drift_wrapper, 155.0,
            funding_rate=0.0012, direction=Direction.LONG, tier=2,
        )
        assert not result.passed

        # Same funding, Tier 3 passes
        result = gm.evaluate(
            mock_drift_wrapper, 155.0,
            funding_rate=0.0012, direction=Direction.LONG, tier=3,
        )
        assert result.passed


class TestGRpc:
    """P7: RPC health gate."""

    def test_healthy_passes(self, mock_drift_wrapper):
        mock_drift_wrapper.rpc_age_s = 0.5
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.passed

    def test_stale_rpc_blocks(self, mock_drift_wrapper):
        mock_drift_wrapper.rpc_age_s = 15.0  # > 10s threshold
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed
        assert result.failed_gate == GateID.G_RPC

    def test_disconnected_blocks(self, mock_drift_wrapper):
        mock_drift_wrapper.is_connected = False
        gm = GateManager()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert not result.passed
        assert result.mode == DegradedMode.FULL_HALT


class TestPrecedence:
    """Gate precedence order — higher gates override lower."""

    def test_kill_overrides_all(self, mock_drift_wrapper):
        """G_KILL (P0) should fire before G_LIQ (P1)."""
        mock_drift_wrapper.get_margin_ratio.return_value = 1.5
        gm = GateManager()
        gm.activate_kill()
        result = gm.evaluate(mock_drift_wrapper, 155.0)
        assert result.failed_gate == GateID.G_KILL  # Not G_LIQ

    def test_liq_overrides_dd(self, mock_drift_wrapper):
        """G_LIQ (P1) should fire before G_DD (P2)."""
        mock_drift_wrapper.get_margin_ratio.return_value = 1.5
        gm = GateManager()
        gm.state.session_hwm = 20.0
        result = gm.evaluate(mock_drift_wrapper, 155.0, current_nav=5.0)
        assert result.failed_gate == GateID.G_LIQ


class TestCooldowns:
    """Edge Case A: Re-entry cooldowns."""

    def test_sl_cooldown(self, mock_drift_wrapper):
        gm = GateManager()
        # Prime HWM with high NAV so G_DD and G_DAY don't trip
        gm.evaluate(mock_drift_wrapper, 155.0, current_nav=100.0)
        gm.record_trade_result(-0.10, Direction.LONG, "sl")
        result = gm.evaluate(
            mock_drift_wrapper, 155.0, direction=Direction.LONG, current_nav=99.9,
        )
        assert not result.passed
        assert "cooldown" in result.reason.lower()

    def test_liq_cooldown(self, mock_drift_wrapper):
        gm = GateManager()
        gm.evaluate(mock_drift_wrapper, 155.0, current_nav=100.0)
        gm.record_trade_result(-0.50, Direction.LONG, "liq")
        result = gm.evaluate(
            mock_drift_wrapper, 155.0, direction=Direction.LONG, current_nav=99.5,
        )
        assert not result.passed

    def test_opposite_direction_not_blocked_by_sl_cooldown(self, mock_drift_wrapper):
        """SL cooldown is direction-specific."""
        gm = GateManager()
        gm.evaluate(mock_drift_wrapper, 155.0, current_nav=100.0)
        gm.record_trade_result(-0.10, Direction.LONG, "sl")
        result = gm.evaluate(
            mock_drift_wrapper, 155.0, direction=Direction.SHORT, current_nav=99.9,
        )
        assert result.passed  # SHORT not blocked by LONG SL cooldown
