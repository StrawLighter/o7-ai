"""
Oracle price feed — subscribes to Drift market data via driftpy WebSocket.

Sets an asyncio.Event on each new oracle price update so the main loop
can implement the hybrid tick cadence (MG Patch 1).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from warpath import config

logger = logging.getLogger(__name__)


@dataclass
class PriceTick:
    price: float
    timestamp: float
    slot: int = 0


class OracleFeed:
    """Wraps driftpy oracle subscription and emits PriceTick events."""

    def __init__(self) -> None:
        self.latest_tick: PriceTick | None = None
        self.price_event: asyncio.Event = asyncio.Event()
        self._running: bool = False
        self._poll_task: asyncio.Task | None = None

    async def start(self, drift_wrapper) -> None:
        """Begin polling oracle price from the subscribed DriftClient."""
        self._drift = drift_wrapper
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("OracleFeed started for market_index=%d", config.PERP_MARKET_INDEX)

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("OracleFeed stopped")

    async def _poll_loop(self) -> None:
        """Poll oracle price at high frequency.

        driftpy's WebSocket subscription keeps the DriftClient state
        up-to-date internally. We poll get_oracle_price() and emit
        events when the price changes. This runs faster than the main
        tick timer to ensure price-reactive ticks.
        """
        last_price: float = 0.0
        poll_interval = 0.05  # 50ms — fast enough to detect sub-tick moves

        while self._running:
            try:
                price = self._drift.get_oracle_price()
                now = time.time()

                if price != last_price and price > 0:
                    last_price = price
                    self.latest_tick = PriceTick(price=price, timestamp=now)
                    self.price_event.set()

            except Exception as e:
                logger.warning("OracleFeed poll error: %s", e)

            await asyncio.sleep(poll_interval)

    async def wait_for_tick(self, timeout: float | None = None) -> PriceTick | None:
        """Wait for the next price update or timeout.

        Used by the hybrid tick loop: whichever fires first
        (price event or timer) drives the next processing cycle.
        """
        try:
            await asyncio.wait_for(self.price_event.wait(), timeout=timeout)
            self.price_event.clear()
            return self.latest_tick
        except asyncio.TimeoutError:
            return self.latest_tick
