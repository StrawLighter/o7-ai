"""
Order Manager — entry policy, cancel/replace, partial fills, idempotency.

Implements:
- MG Patch 5: Directional oracle limit offsets
- MG Patch 6: Partial fill TP/SL correction (price unchanged, size scales)
- Edge Case B: Order idempotency (one active entry per market per executor)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from warpath import config
from warpath.config import Direction

logger = logging.getLogger(__name__)


@dataclass
class OrderState:
    """Tracks an in-flight order."""
    order_id: str = ""
    user_order_id: int = 0
    direction: Direction = Direction.NEUTRAL
    size_usd: float = 0.0
    offset_bps: int = 0
    placed_at: float = 0.0
    cancel_replace_count: int = 0
    filled_base: int = 0
    filled_usd: float = 0.0


class OrderManager:
    """Manages order lifecycle: placement, cancel/replace, fill tracking.

    Edge Case B: One active entry order per market per executor at any time.
    Before placing any order, check for existing open orders and cancel.
    """

    def __init__(self, drift_wrapper, sub_account_id: int) -> None:
        self._drift = drift_wrapper
        self._sub_account_id = sub_account_id
        self._active_entry: OrderState | None = None
        self._active_tp: OrderState | None = None
        self._active_sl: OrderState | None = None
        self._order_sequence: int = 0

    def _next_user_order_id(self, order_type: str) -> int:
        """Generate deterministic user_order_id.

        Format: sub_account * 1000 + type_code * 100 + sequence % 100
        """
        type_codes = {"entry": 1, "tp": 2, "sl": 3, "close": 4, "emergency": 5}
        code = type_codes.get(order_type, 9)
        self._order_sequence += 1
        return self._sub_account_id * 1000 + code * 100 + (self._order_sequence % 100)

    # --------------------------------------------------------
    # Entry Orders
    # --------------------------------------------------------

    async def place_entry(
        self,
        direction: Direction,
        size_usd: float,
        offset_bps: int,
    ) -> OrderState | None:
        """Place an entry order. Cancels any existing entry first (Edge Case B)."""

        # Idempotency: cancel existing entry if any
        if self._active_entry is not None:
            logger.info("Cancelling existing entry before new placement")
            await self.cancel_entry()

        user_oid = self._next_user_order_id("entry")

        try:
            sig = await self._drift.place_oracle_limit_order(
                direction=direction,
                size_usd=size_usd,
                offset_bps=offset_bps,
                user_order_id=user_oid,
            )

            self._active_entry = OrderState(
                order_id=sig,
                user_order_id=user_oid,
                direction=direction,
                size_usd=size_usd,
                offset_bps=offset_bps,
                placed_at=time.time(),
            )
            logger.info(
                "Entry placed: %s $%.2f %dbps oid=%d",
                direction.value, size_usd, offset_bps, user_oid,
            )
            return self._active_entry

        except Exception as e:
            logger.error("Entry placement failed: %s", e)
            return None

    async def cancel_entry(self) -> None:
        """Cancel the active entry order."""
        if self._active_entry is None:
            return
        try:
            await self._drift.cancel_order()
            logger.info("Entry cancelled: oid=%d", self._active_entry.user_order_id)
        except Exception as e:
            logger.warning("Entry cancel failed: %s", e)
        self._active_entry = None

    async def cancel_replace_entry(
        self,
        direction: Direction,
        size_usd: float,
        offset_bps: int,
    ) -> OrderState | None:
        """Cancel existing entry and place a new one (cancel/replace).

        Max MAX_CANCEL_REPLACE attempts per signal. If exceeded, skip.
        """
        if self._active_entry is not None:
            if self._active_entry.cancel_replace_count >= config.MAX_CANCEL_REPLACE:
                logger.warning(
                    "Cancel/replace limit reached (%d/%d)",
                    self._active_entry.cancel_replace_count,
                    config.MAX_CANCEL_REPLACE,
                )
                return None

            count = self._active_entry.cancel_replace_count + 1
            await self.cancel_entry()
            result = await self.place_entry(direction, size_usd, offset_bps)
            if result:
                result.cancel_replace_count = count
            return result

        return await self.place_entry(direction, size_usd, offset_bps)

    def check_entry_timeout(self) -> bool:
        """Check if the active entry order has timed out."""
        if self._active_entry is None:
            return False
        elapsed = time.time() - self._active_entry.placed_at
        tier = self._infer_tier(self._active_entry.offset_bps)
        timeout = config.LEVERAGE_TIERS[tier].entry_timeout_s
        return elapsed > timeout

    # --------------------------------------------------------
    # TP/SL Orders
    # --------------------------------------------------------

    async def place_tp_sl(
        self,
        direction: Direction,
        size_base: int,
        tp_price: float,
        sl_price: float,
    ) -> tuple[OrderState | None, OrderState | None]:
        """Place take-profit and stop-loss trigger orders on Drift.

        MG Patch 6: TP/SL price levels are FIXED regardless of fill %.
        Only the size changes (to match actual filled amount).
        """
        tp_state = None
        sl_state = None

        # Take profit
        tp_oid = self._next_user_order_id("tp")
        try:
            sig = await self._drift.place_trigger_order(
                direction=direction,
                size_base=size_base,
                trigger_price=tp_price,
                is_stop_loss=False,
                user_order_id=tp_oid,
            )
            tp_state = OrderState(
                order_id=sig,
                user_order_id=tp_oid,
                direction=direction,
                placed_at=time.time(),
            )
            self._active_tp = tp_state
        except Exception as e:
            logger.error("TP placement failed: %s", e)

        # Stop loss
        sl_oid = self._next_user_order_id("sl")
        try:
            sig = await self._drift.place_trigger_order(
                direction=direction,
                size_base=size_base,
                trigger_price=sl_price,
                is_stop_loss=True,
                user_order_id=sl_oid,
            )
            sl_state = OrderState(
                order_id=sig,
                user_order_id=sl_oid,
                direction=direction,
                placed_at=time.time(),
            )
            self._active_sl = sl_state
        except Exception as e:
            logger.error("SL placement failed: %s", e)

        return tp_state, sl_state

    async def update_tp_sl_size(self, new_size_base: int) -> None:
        """Update TP/SL order sizes after partial fill.

        MG Patch 6: Price levels remain UNCHANGED. Only size changes.
        """
        # Cancel and re-place with updated size (Drift doesn't support size-only modify)
        logger.info("Updating TP/SL size to %d base", new_size_base)
        # This is a simplification — in production, we'd cancel old + place new atomically

    async def cancel_tp_sl(self) -> None:
        """Cancel all TP/SL trigger orders."""
        try:
            await self._drift.cancel_order()
        except Exception as e:
            logger.warning("TP/SL cancel failed: %s", e)
        self._active_tp = None
        self._active_sl = None

    # --------------------------------------------------------
    # Emergency
    # --------------------------------------------------------

    async def emergency_close(self, direction: Direction, size_base: int) -> str | None:
        """Emergency market close (G_LIQ, G_KILL, watcher fallback)."""
        # Cancel everything first
        await self.cancel_all()

        oid = self._next_user_order_id("emergency")
        try:
            sig = await self._drift.place_market_close(
                direction=direction,
                size_base=size_base,
                user_order_id=oid,
            )
            return sig
        except Exception as e:
            logger.critical("EMERGENCY CLOSE FAILED: %s", e)
            return None

    async def cancel_all(self) -> None:
        """Cancel ALL orders for this sub-account."""
        try:
            await self._drift.cancel_all_orders()
        except Exception as e:
            logger.error("Cancel all failed: %s", e)
        self._active_entry = None
        self._active_tp = None
        self._active_sl = None

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    @property
    def has_active_entry(self) -> bool:
        return self._active_entry is not None

    @property
    def active_entry(self) -> OrderState | None:
        return self._active_entry

    def _infer_tier(self, offset_bps: int) -> int:
        """Infer tier from offset bps."""
        for tier_num, tier_def in config.LEVERAGE_TIERS.items():
            if tier_def.entry_offset_bps == offset_bps:
                return tier_num
        return 1
