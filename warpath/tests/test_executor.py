"""Tests for Executor state machine — all transitions."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from warpath import config
from warpath.config import Direction, ExecutorState
from warpath.execution.executor import Executor, _VALID_TRANSITIONS
from warpath.execution.order_manager import OrderManager
from warpath.monitoring.telemetry import Telemetry


@pytest.fixture
def executor(mock_drift_wrapper):
    """Create an Executor with mocked dependencies."""
    om = OrderManager(mock_drift_wrapper, sub_account_id=0)
    telemetry = Telemetry()
    return Executor(om, telemetry, sub_account_id=0)


class TestStateTransitions:
    """All valid state transitions and invalid transition rejection."""

    def test_initial_state_is_closed(self, executor):
        assert executor.state == ExecutorState.CLOSED

    def test_closed_to_pending(self, executor):
        assert executor._transition(ExecutorState.PENDING)
        assert executor.state == ExecutorState.PENDING

    def test_pending_to_active(self, executor):
        executor._transition(ExecutorState.PENDING)
        assert executor._transition(ExecutorState.ACTIVE)
        assert executor.state == ExecutorState.ACTIVE

    def test_pending_to_cancelled(self, executor):
        executor._transition(ExecutorState.PENDING)
        assert executor._transition(ExecutorState.CANCELLED)
        assert executor.state == ExecutorState.CANCELLED

    def test_active_to_closing(self, executor):
        executor._transition(ExecutorState.PENDING)
        executor._transition(ExecutorState.ACTIVE)
        assert executor._transition(ExecutorState.CLOSING)
        assert executor.state == ExecutorState.CLOSING

    def test_active_to_emergency(self, executor):
        executor._transition(ExecutorState.PENDING)
        executor._transition(ExecutorState.ACTIVE)
        assert executor._transition(ExecutorState.EMERGENCY)
        assert executor.state == ExecutorState.EMERGENCY

    def test_closing_to_closed(self, executor):
        executor._transition(ExecutorState.PENDING)
        executor._transition(ExecutorState.ACTIVE)
        executor._transition(ExecutorState.CLOSING)
        assert executor._transition(ExecutorState.CLOSED)
        assert executor.state == ExecutorState.CLOSED

    def test_emergency_to_closed(self, executor):
        executor._transition(ExecutorState.PENDING)
        executor._transition(ExecutorState.ACTIVE)
        executor._transition(ExecutorState.EMERGENCY)
        assert executor._transition(ExecutorState.CLOSED)
        assert executor.state == ExecutorState.CLOSED

    # Invalid transitions
    def test_closed_to_active_invalid(self, executor):
        assert not executor._transition(ExecutorState.ACTIVE)
        assert executor.state == ExecutorState.CLOSED

    def test_pending_to_closing_invalid(self, executor):
        executor._transition(ExecutorState.PENDING)
        assert not executor._transition(ExecutorState.CLOSING)
        assert executor.state == ExecutorState.PENDING

    def test_closing_to_emergency_invalid(self, executor):
        executor._transition(ExecutorState.PENDING)
        executor._transition(ExecutorState.ACTIVE)
        executor._transition(ExecutorState.CLOSING)
        assert not executor._transition(ExecutorState.EMERGENCY)

    def test_all_valid_transitions_covered(self):
        """Verify the transition map is complete."""
        for state in ExecutorState:
            assert state in _VALID_TRANSITIONS


class TestEntry:
    """Entry flow: CLOSED → PENDING."""

    @pytest.mark.asyncio
    async def test_enter_transitions_to_pending(self, executor, mock_drift_wrapper):
        result = await executor.enter(
            direction=Direction.LONG,
            size_usd=5.0,
            offset_bps=5,
            leverage=20.0,
            tier=3,
            atr=1.5,
            oracle_price=155.0,
        )
        assert result is True
        assert executor.state == ExecutorState.PENDING

    @pytest.mark.asyncio
    async def test_enter_computes_stops(self, executor, mock_drift_wrapper):
        await executor.enter(
            direction=Direction.LONG,
            size_usd=5.0, offset_bps=5, leverage=20.0, tier=3,
            atr=1.5, oracle_price=155.0,
        )
        assert executor.sl_price < 155.0  # SL below entry for LONG
        assert executor.tp_price > 155.0  # TP above entry for LONG

    @pytest.mark.asyncio
    async def test_short_stops_reversed(self, executor, mock_drift_wrapper):
        await executor.enter(
            direction=Direction.SHORT,
            size_usd=5.0, offset_bps=5, leverage=20.0, tier=3,
            atr=1.5, oracle_price=155.0,
        )
        assert executor.sl_price > 155.0  # SL above entry for SHORT
        assert executor.tp_price < 155.0  # TP below entry for SHORT


class TestFillDetection:
    """PENDING → ACTIVE on fill."""

    @pytest.mark.asyncio
    async def test_no_fill_stays_pending(self, executor, mock_drift_wrapper):
        await executor.enter(
            direction=Direction.LONG,
            size_usd=5.0, offset_bps=5, leverage=20.0, tier=3,
            atr=1.5, oracle_price=155.0,
        )
        mock_drift_wrapper.get_perp_position.return_value = None
        result = await executor.check_fill(mock_drift_wrapper)
        assert not result
        assert executor.state == ExecutorState.PENDING


class TestMAEMFE:
    """Max Adverse/Favorable Excursion tracking."""

    def test_mae_mfe_update(self, executor):
        executor._metrics.entry_price = 155.0
        executor._metrics.direction = Direction.LONG
        executor.state = ExecutorState.ACTIVE

        # Price moves up
        executor._update_mae_mfe(157.0)
        assert executor.metrics.mfe == 2.0
        assert executor.metrics.mae == 0.0

        # Price pulls back
        executor._update_mae_mfe(153.0)
        assert executor.metrics.mae == -2.0
        assert executor.metrics.mfe == 2.0  # MFE doesn't decrease


class TestIsIdle:
    """Executor idle state checks."""

    def test_idle_when_closed(self, executor):
        assert executor.is_idle

    @pytest.mark.asyncio
    async def test_not_idle_when_pending(self, executor, mock_drift_wrapper):
        await executor.enter(
            direction=Direction.LONG,
            size_usd=5.0, offset_bps=5, leverage=20.0, tier=3,
            atr=1.5, oracle_price=155.0,
        )
        assert not executor.is_idle
