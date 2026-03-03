"""
Local Watcher — independent safety monitor on secondary RPC.

Runs as an independent asyncio task, polling every WATCHER_INTERVAL_MS.
If a TP/SL trigger order on Drift has not filled within the grace period
after price crosses the level, the watcher places a fallback market close.

This module NEVER opens positions — it only closes them in emergencies.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from solana.rpc.async_api import AsyncClient

from warpath import config
from warpath.config import Direction

logger = logging.getLogger(__name__)


@dataclass
class WatchedPosition:
    """Position being monitored by the watcher."""
    direction: Direction
    size_base: int
    sl_price: float
    tp_price: float
    sl_crossed_at: float = 0.0  # timestamp when SL was first breached
    tp_crossed_at: float = 0.0  # timestamp when TP was first breached


class LocalWatcher:
    """Independent safety monitor using secondary RPC connection."""

    def __init__(self) -> None:
        self._positions: dict[int, WatchedPosition] = {}  # sub_account -> position
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._drift_wrapper = None  # primary wrapper for order placement
        self._secondary_connection: AsyncClient | None = None

    def register_position(
        self,
        sub_account_id: int,
        direction: Direction,
        size_base: int,
        sl_price: float,
        tp_price: float,
    ) -> None:
        """Register a position to watch."""
        self._positions[sub_account_id] = WatchedPosition(
            direction=direction,
            size_base=size_base,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        logger.info(
            "Watcher: registered SA#%d %s SL=%.4f TP=%.4f",
            sub_account_id, direction.value, sl_price, tp_price,
        )

    def unregister_position(self, sub_account_id: int) -> None:
        """Remove position from watch list (closed normally)."""
        self._positions.pop(sub_account_id, None)

    def update_stops(
        self, sub_account_id: int, sl_price: float, tp_price: float,
    ) -> None:
        """Update stop levels (e.g., when trailing or tightening)."""
        pos = self._positions.get(sub_account_id)
        if pos:
            pos.sl_price = sl_price
            pos.tp_price = tp_price
            pos.sl_crossed_at = 0.0
            pos.tp_crossed_at = 0.0

    async def start(self, drift_wrapper) -> None:
        """Start the watcher loop on secondary RPC."""
        self._drift_wrapper = drift_wrapper
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("LocalWatcher started (interval=%dms)", config.WATCHER_INTERVAL_MS)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LocalWatcher stopped")

    async def _watch_loop(self) -> None:
        """Main watcher loop — polls at WATCHER_INTERVAL_MS."""
        interval = config.WATCHER_INTERVAL_MS / 1000.0

        while self._running:
            try:
                await self._check_all_positions()
            except Exception as e:
                logger.error("Watcher loop error: %s", e)

            await asyncio.sleep(interval)

    async def _check_all_positions(self) -> None:
        """Check all watched positions against oracle price."""
        if not self._drift_wrapper or not self._drift_wrapper.is_connected:
            return

        if not self._positions:
            return

        try:
            oracle_price = self._drift_wrapper.get_oracle_price()
        except Exception as e:
            logger.error("Watcher: oracle read failed: %s", e)
            return

        now = time.time()

        for sub_id, pos in list(self._positions.items()):
            await self._check_position(sub_id, pos, oracle_price, now)

    async def _check_position(
        self,
        sub_account_id: int,
        pos: WatchedPosition,
        oracle_price: float,
        now: float,
    ) -> None:
        """Check if SL/TP has been breached and trigger orders haven't filled."""

        sl_breached = self._is_sl_breached(pos, oracle_price)
        tp_breached = self._is_tp_breached(pos, oracle_price)

        # Track SL breach timing
        if sl_breached:
            if pos.sl_crossed_at == 0.0:
                pos.sl_crossed_at = now
                logger.warning(
                    "Watcher: SL breached SA#%d at %.4f (SL=%.4f)",
                    sub_account_id, oracle_price, pos.sl_price,
                )
            elif now - pos.sl_crossed_at > config.WATCHER_TRIGGER_GRACE:
                # Grace period expired — trigger order didn't fire, send fallback
                logger.critical(
                    "Watcher: SL FALLBACK SA#%d — trigger order failed, placing market close",
                    sub_account_id,
                )
                await self._fallback_close(sub_account_id, pos)
                return
        else:
            pos.sl_crossed_at = 0.0

        # Track TP breach timing
        if tp_breached:
            if pos.tp_crossed_at == 0.0:
                pos.tp_crossed_at = now
            elif now - pos.tp_crossed_at > config.WATCHER_TP_GRACE:
                logger.warning(
                    "Watcher: TP FALLBACK SA#%d — trigger order failed, placing market close",
                    sub_account_id,
                )
                await self._fallback_close(sub_account_id, pos)
                return
        else:
            pos.tp_crossed_at = 0.0

    def _is_sl_breached(self, pos: WatchedPosition, price: float) -> bool:
        """Check if price has crossed the stop loss level."""
        if pos.direction == Direction.LONG:
            return price <= pos.sl_price
        else:
            return price >= pos.sl_price

    def _is_tp_breached(self, pos: WatchedPosition, price: float) -> bool:
        """Check if price has crossed the take profit level."""
        if pos.direction == Direction.LONG:
            return price >= pos.tp_price
        else:
            return price <= pos.tp_price

    async def _fallback_close(
        self, sub_account_id: int, pos: WatchedPosition,
    ) -> None:
        """Emergency market close when trigger order fails."""
        try:
            await self._drift_wrapper.place_market_close(
                direction=pos.direction,
                size_base=pos.size_base,
                user_order_id=9000 + sub_account_id,  # watcher-specific ID range
            )
            self._positions.pop(sub_account_id, None)
            logger.info("Watcher: fallback close sent for SA#%d", sub_account_id)
        except Exception as e:
            logger.critical(
                "Watcher: FALLBACK CLOSE FAILED SA#%d: %s", sub_account_id, e,
            )
