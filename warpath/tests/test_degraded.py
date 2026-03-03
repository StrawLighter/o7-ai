"""Tests for degraded mode state machine — all transitions."""

from __future__ import annotations

import time

import pytest

from warpath.config import DegradedMode
from warpath.risk.degraded_mode import DegradedModeManager


class TestTransitions:
    """Valid and invalid mode transitions."""

    def test_initial_mode_is_normal(self):
        dm = DegradedModeManager()
        assert dm.mode == DegradedMode.NORMAL

    def test_normal_to_safe_manage(self):
        dm = DegradedModeManager()
        assert dm.transition(DegradedMode.SAFE_MANAGE, "test")
        assert dm.mode == DegradedMode.SAFE_MANAGE

    def test_normal_to_full_halt(self):
        dm = DegradedModeManager()
        assert dm.transition(DegradedMode.FULL_HALT, "kill")
        assert dm.mode == DegradedMode.FULL_HALT

    def test_safe_manage_to_full_halt(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.SAFE_MANAGE, "test")
        assert dm.transition(DegradedMode.FULL_HALT, "escalation")
        assert dm.mode == DegradedMode.FULL_HALT

    def test_safe_manage_to_normal(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.SAFE_MANAGE, "test")
        assert dm.transition(DegradedMode.NORMAL, "recovered")
        assert dm.mode == DegradedMode.NORMAL

    def test_full_halt_to_normal(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.FULL_HALT, "kill")
        assert dm.transition(DegradedMode.NORMAL, "manual reset")

    # Invalid transitions
    def test_full_halt_to_safe_manage_invalid(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.FULL_HALT, "kill")
        assert not dm.transition(DegradedMode.SAFE_MANAGE, "invalid")
        assert dm.mode == DegradedMode.FULL_HALT

    def test_same_mode_returns_false(self):
        dm = DegradedModeManager()
        assert not dm.transition(DegradedMode.NORMAL, "no change")


class TestProperties:
    """Mode-dependent property checks."""

    def test_normal_can_open(self):
        dm = DegradedModeManager()
        assert dm.can_open_positions
        assert not dm.should_tighten_stops
        assert not dm.should_flatten

    def test_safe_manage_no_open(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.SAFE_MANAGE, "test")
        assert not dm.can_open_positions
        assert dm.should_tighten_stops
        assert not dm.should_flatten

    def test_full_halt_flatten(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.FULL_HALT, "kill")
        assert not dm.can_open_positions
        assert dm.should_flatten


class TestRecovery:
    """Recovery from degraded modes."""

    def test_full_halt_no_auto_recovery(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.FULL_HALT, "kill")
        assert not dm.check_recovery(all_gates_clear=True)
        assert dm.mode == DegradedMode.FULL_HALT  # No change

    def test_manual_reset_from_full_halt(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.FULL_HALT, "kill")
        assert dm.manual_reset()
        assert dm.mode == DegradedMode.NORMAL

    def test_safe_manage_recovery_needs_time(self):
        dm = DegradedModeManager()
        dm._all_clear_required_s = 0.1  # Short for testing
        dm.transition(DegradedMode.SAFE_MANAGE, "test")

        # First check starts timer
        dm.check_recovery(all_gates_clear=True)
        assert dm.mode == DegradedMode.SAFE_MANAGE

        # Wait for recovery period
        time.sleep(0.15)
        dm.check_recovery(all_gates_clear=True)
        assert dm.mode == DegradedMode.NORMAL

    def test_interruption_resets_timer(self):
        dm = DegradedModeManager()
        dm._all_clear_required_s = 0.1
        dm.transition(DegradedMode.SAFE_MANAGE, "test")

        dm.check_recovery(all_gates_clear=True)
        dm.check_recovery(all_gates_clear=False)  # Interrupt
        time.sleep(0.15)
        dm.check_recovery(all_gates_clear=True)
        # Timer reset, so still in SAFE_MANAGE
        assert dm.mode == DegradedMode.SAFE_MANAGE


class TestEscalation:
    """Mode escalation from gate results."""

    def test_escalate_normal_to_safe_manage(self):
        dm = DegradedModeManager()
        dm.update_from_gate_result(DegradedMode.SAFE_MANAGE, "G_DD trip")
        assert dm.mode == DegradedMode.SAFE_MANAGE

    def test_escalate_safe_manage_to_full_halt(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.SAFE_MANAGE, "test")
        dm.update_from_gate_result(DegradedMode.FULL_HALT, "G_KILL")
        assert dm.mode == DegradedMode.FULL_HALT

    def test_no_deescalation_via_gate(self):
        dm = DegradedModeManager()
        dm.transition(DegradedMode.SAFE_MANAGE, "test")
        dm.update_from_gate_result(DegradedMode.NORMAL, "gates clear")
        assert dm.mode == DegradedMode.SAFE_MANAGE  # No deescalation

    def test_status_dict(self):
        dm = DegradedModeManager()
        status = dm.status
        assert status["mode"] == "NORMAL"
        assert "duration_s" in status
        assert status["can_open"] is True
