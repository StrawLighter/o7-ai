"""Shared test fixtures for WARPATH test suite."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from warpath.config import Direction
from warpath.data.candle_builder import Candle


@pytest.fixture
def sample_candles() -> list[Candle]:
    """Generate 30 sample candles with realistic SOL-PERP price action."""
    base_price = 150.0
    candles = []
    t = time.time() - 30 * 300  # 30 × 5min ago

    # Simulate an uptrend with pullbacks
    prices = [
        150.0, 151.2, 152.5, 151.8, 153.0,  # up
        154.2, 153.5, 155.0, 156.3, 155.8,  # up with pullback
        157.0, 158.5, 157.2, 159.0, 160.1,  # up
        159.5, 158.0, 157.5, 159.2, 160.8,  # consolidation
        161.5, 162.0, 163.2, 162.5, 164.0,  # breakout
        163.0, 165.2, 166.0, 165.5, 167.0,  # continuation
    ]

    for i, p in enumerate(prices):
        noise_h = abs(p * 0.005)
        noise_l = abs(p * 0.004)
        candles.append(Candle(
            timestamp=t + i * 300,
            open=p - 0.3,
            high=p + noise_h,
            low=p - noise_l,
            close=p,
            volume=100 + i * 10,
            timeframe="5m",
            closed=True,
        ))

    return candles


@pytest.fixture
def downtrend_candles() -> list[Candle]:
    """30 candles showing a downtrend."""
    candles = []
    t = time.time() - 30 * 300

    prices = [
        170.0, 169.0, 168.2, 169.5, 167.0,
        166.0, 167.2, 165.5, 164.0, 165.0,
        163.5, 162.0, 163.0, 161.5, 160.0,
        161.0, 159.5, 158.0, 159.0, 157.5,
        156.0, 157.0, 155.5, 154.0, 155.0,
        153.5, 152.0, 153.0, 151.5, 150.0,
    ]

    for i, p in enumerate(prices):
        candles.append(Candle(
            timestamp=t + i * 300,
            open=p + 0.5,
            high=p + abs(p * 0.004),
            low=p - abs(p * 0.005),
            close=p,
            volume=100 + i * 5,
            timeframe="5m",
            closed=True,
        ))

    return candles


@pytest.fixture
def range_candles() -> list[Candle]:
    """30 candles showing sideways/range-bound action."""
    candles = []
    t = time.time() - 30 * 300

    prices = [
        155.0, 155.5, 154.8, 155.2, 154.5,
        155.8, 155.0, 154.2, 155.5, 155.1,
        154.7, 155.3, 155.0, 154.9, 155.4,
        155.2, 154.6, 155.1, 155.3, 154.8,
        155.0, 155.4, 154.7, 155.2, 155.0,
        154.9, 155.3, 155.1, 154.8, 155.0,
    ]

    for i, p in enumerate(prices):
        candles.append(Candle(
            timestamp=t + i * 300,
            open=p - 0.1,
            high=p + 0.3,
            low=p - 0.3,
            close=p,
            volume=80,
            timeframe="5m",
            closed=True,
        ))

    return candles


@pytest.fixture
def mock_drift_wrapper() -> MagicMock:
    """Mock DriftWrapper for testing without real Drift connection."""
    mock = MagicMock()
    mock.is_connected = True
    mock.rpc_age_s = 0.5
    mock.get_oracle_price.return_value = 155.0
    mock.get_margin_ratio.return_value = 5.0
    mock.get_free_collateral.return_value = 10.0
    mock.get_nav.return_value = 10.0
    mock.get_unrealized_pnl.return_value = 0.0
    mock.get_funding_rate.return_value = 0.0001
    mock.get_perp_position.return_value = None
    mock.get_open_orders.return_value = []

    # Async methods
    mock.place_oracle_limit_order = AsyncMock(return_value="sig_entry_123")
    mock.place_trigger_order = AsyncMock(return_value="sig_trigger_123")
    mock.place_market_close = AsyncMock(return_value="sig_close_123")
    mock.cancel_order = AsyncMock()
    mock.cancel_all_orders = AsyncMock()

    return mock
