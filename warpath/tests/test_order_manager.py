"""Tests for order manager — oracle offsets, cancel/replace, idempotency."""

from __future__ import annotations

import pytest

from warpath.config import Direction
from warpath.execution.order_manager import OrderManager


@pytest.fixture
def om(mock_drift_wrapper):
    return OrderManager(mock_drift_wrapper, sub_account_id=0)


class TestOrderPlacement:

    @pytest.mark.asyncio
    async def test_place_entry_returns_state(self, om):
        result = await om.place_entry(Direction.LONG, 5.0, 5)
        assert result is not None
        assert result.direction == Direction.LONG
        assert result.size_usd == 5.0
        assert result.offset_bps == 5

    @pytest.mark.asyncio
    async def test_has_active_entry(self, om):
        assert not om.has_active_entry
        await om.place_entry(Direction.LONG, 5.0, 5)
        assert om.has_active_entry

    @pytest.mark.asyncio
    async def test_user_order_id_increments(self, om):
        r1 = await om.place_entry(Direction.LONG, 5.0, 5)
        await om.cancel_entry()
        r2 = await om.place_entry(Direction.LONG, 5.0, 5)
        assert r1 is not None and r2 is not None
        assert r1.user_order_id != r2.user_order_id


class TestIdempotency:
    """Edge Case B: One active entry per market per executor."""

    @pytest.mark.asyncio
    async def test_cancels_existing_before_new(self, om, mock_drift_wrapper):
        """Placing a new entry should cancel the existing one first."""
        await om.place_entry(Direction.LONG, 5.0, 5)
        assert om.has_active_entry

        # Place another — should cancel first
        await om.place_entry(Direction.SHORT, 3.0, 3)
        assert om.has_active_entry
        assert om.active_entry.direction == Direction.SHORT
        # cancel_order should have been called
        mock_drift_wrapper.cancel_order.assert_called()


class TestCancelReplace:
    """Cancel/replace cadence — max 3 per signal."""

    @pytest.mark.asyncio
    async def test_cancel_replace_increments(self, om):
        await om.place_entry(Direction.LONG, 5.0, 5)
        result = await om.cancel_replace_entry(Direction.LONG, 5.0, 5)
        assert result is not None
        assert result.cancel_replace_count == 1

    @pytest.mark.asyncio
    async def test_cancel_replace_limit(self, om):
        await om.place_entry(Direction.LONG, 5.0, 5)
        for _ in range(3):
            await om.cancel_replace_entry(Direction.LONG, 5.0, 5)

        # 4th attempt should be rejected
        result = await om.cancel_replace_entry(Direction.LONG, 5.0, 5)
        assert result is None


class TestEmergencyClose:

    @pytest.mark.asyncio
    async def test_emergency_close(self, om, mock_drift_wrapper):
        sig = await om.emergency_close(Direction.LONG, 1000000)
        assert sig is not None
        mock_drift_wrapper.place_market_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_all(self, om, mock_drift_wrapper):
        await om.place_entry(Direction.LONG, 5.0, 5)
        await om.cancel_all()
        assert not om.has_active_entry
        mock_drift_wrapper.cancel_all_orders.assert_called()
