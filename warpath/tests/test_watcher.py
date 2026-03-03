"""Tests for local watcher — fallback detection + order placement."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from warpath.config import Direction
from warpath.risk.watcher import LocalWatcher, WatchedPosition


class TestPositionRegistration:

    def test_register_position(self):
        w = LocalWatcher()
        w.register_position(0, Direction.LONG, 1000000, sl_price=150.0, tp_price=160.0)
        assert 0 in w._positions
        assert w._positions[0].direction == Direction.LONG

    def test_unregister_position(self):
        w = LocalWatcher()
        w.register_position(0, Direction.LONG, 1000000, 150.0, 160.0)
        w.unregister_position(0)
        assert 0 not in w._positions

    def test_update_stops(self):
        w = LocalWatcher()
        w.register_position(0, Direction.LONG, 1000000, 150.0, 160.0)
        w.update_stops(0, sl_price=151.0, tp_price=159.0)
        assert w._positions[0].sl_price == 151.0
        assert w._positions[0].tp_price == 159.0


class TestBreachDetection:

    def test_sl_breach_long(self):
        w = LocalWatcher()
        pos = WatchedPosition(Direction.LONG, 1000000, sl_price=150.0, tp_price=160.0)
        assert w._is_sl_breached(pos, 149.5)  # Below SL
        assert not w._is_sl_breached(pos, 151.0)  # Above SL

    def test_sl_breach_short(self):
        w = LocalWatcher()
        pos = WatchedPosition(Direction.SHORT, 1000000, sl_price=160.0, tp_price=150.0)
        assert w._is_sl_breached(pos, 160.5)  # Above SL
        assert not w._is_sl_breached(pos, 159.0)  # Below SL

    def test_tp_breach_long(self):
        w = LocalWatcher()
        pos = WatchedPosition(Direction.LONG, 1000000, sl_price=150.0, tp_price=160.0)
        assert w._is_tp_breached(pos, 160.5)  # Above TP
        assert not w._is_tp_breached(pos, 159.0)  # Below TP

    def test_tp_breach_short(self):
        w = LocalWatcher()
        pos = WatchedPosition(Direction.SHORT, 1000000, sl_price=160.0, tp_price=150.0)
        assert w._is_tp_breached(pos, 149.5)  # Below TP
        assert not w._is_tp_breached(pos, 151.0)  # Above TP


class TestFallbackTrigger:

    @pytest.mark.asyncio
    async def test_sl_breach_with_grace_fires_fallback(self, mock_drift_wrapper):
        w = LocalWatcher()
        w._drift_wrapper = mock_drift_wrapper
        mock_drift_wrapper.get_oracle_price.return_value = 149.0

        w.register_position(0, Direction.LONG, 1000000, sl_price=150.0, tp_price=160.0)

        # First check — records breach time
        now = time.time()
        await w._check_position(0, w._positions[0], 149.0, now)
        assert w._positions[0].sl_crossed_at > 0

        # After grace period — should fire fallback
        await w._check_position(0, w._positions[0], 149.0, now + 6.0)
        mock_drift_wrapper.place_market_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_sl_recovery_resets_timer(self, mock_drift_wrapper):
        w = LocalWatcher()
        w._drift_wrapper = mock_drift_wrapper

        w.register_position(0, Direction.LONG, 1000000, sl_price=150.0, tp_price=160.0)

        # Breach
        now = time.time()
        await w._check_position(0, w._positions[0], 149.0, now)
        assert w._positions[0].sl_crossed_at > 0

        # Recovery — price back above SL
        await w._check_position(0, w._positions[0], 151.0, now + 2.0)
        assert w._positions[0].sl_crossed_at == 0.0  # Reset

    @pytest.mark.asyncio
    async def test_no_positions_noop(self, mock_drift_wrapper):
        w = LocalWatcher()
        w._drift_wrapper = mock_drift_wrapper
        await w._check_all_positions()  # Should not crash
