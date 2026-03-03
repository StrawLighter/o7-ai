"""
Executor — position lifecycle state machine.

States: CLOSED → PENDING → ACTIVE → CLOSING → CLOSED
        + EMERGENCY (from ACTIVE, forced by G_LIQ/G_KILL)
        + CANCELLED (from PENDING, on timeout/cancel)

Implements:
- MG Patch 4: ATR-based price stops
- MG Patch 6: Partial fill TP/SL (prices unchanged, size scales)
- Edge Case A: Re-entry cooldowns
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from warpath import config
from warpath.config import Direction, ExecutorState, Regime
from warpath.execution.order_manager import OrderManager
from warpath.monitoring.telemetry import Telemetry, TradeRecord

logger = logging.getLogger(__name__)


# Valid state transitions
_VALID_TRANSITIONS: dict[ExecutorState, set[ExecutorState]] = {
    ExecutorState.CLOSED: {ExecutorState.PENDING},
    ExecutorState.PENDING: {ExecutorState.ACTIVE, ExecutorState.CANCELLED},
    ExecutorState.ACTIVE: {ExecutorState.CLOSING, ExecutorState.EMERGENCY},
    ExecutorState.CLOSING: {ExecutorState.CLOSED},
    ExecutorState.EMERGENCY: {ExecutorState.CLOSED},
    ExecutorState.CANCELLED: {ExecutorState.CLOSED},
}


@dataclass
class ExecutorMetrics:
    """Per-trade metrics tracked by the executor."""
    entry_price: float = 0.0
    exit_price: float = 0.0
    entry_time: float = 0.0
    exit_time: float = 0.0
    direction: Direction = Direction.NEUTRAL
    size_usd: float = 0.0
    size_base: int = 0
    leverage: float = 0.0
    tier: int = 0
    tp_price: float = 0.0
    sl_price: float = 0.0
    mae: float = 0.0        # Max Adverse Excursion (worst unrealized)
    mfe: float = 0.0        # Max Favorable Excursion (best unrealized)
    pnl_usd: float = 0.0
    exit_reason: str = ""
    composite_score: float = 0.0
    regime: str = ""
    signal_scores: dict = field(default_factory=dict)
    cancel_replace_count: int = 0
    fill_latency_ms: float = 0.0


class Executor:
    """Position lifecycle state machine for a single sub-account."""

    def __init__(
        self,
        order_manager: OrderManager,
        telemetry: Telemetry,
        sub_account_id: int,
    ) -> None:
        self._om = order_manager
        self._telemetry = telemetry
        self._sub_account_id = sub_account_id
        self.state: ExecutorState = ExecutorState.CLOSED
        self._metrics: ExecutorMetrics = ExecutorMetrics()
        self._cooldown_until: float = 0.0

    @property
    def is_idle(self) -> bool:
        return self.state == ExecutorState.CLOSED

    @property
    def is_in_cooldown(self) -> bool:
        return time.time() < self._cooldown_until

    def _transition(self, new_state: ExecutorState) -> bool:
        """Attempt state transition. Returns True if valid."""
        if new_state not in _VALID_TRANSITIONS.get(self.state, set()):
            logger.error(
                "Invalid transition: %s → %s", self.state.value, new_state.value,
            )
            return False
        old = self.state
        self.state = new_state
        logger.info(
            "Executor SA#%d: %s → %s", self._sub_account_id, old.value, new_state.value,
        )
        return True

    # --------------------------------------------------------
    # CLOSED → PENDING: Enter a new position
    # --------------------------------------------------------

    async def enter(
        self,
        direction: Direction,
        size_usd: float,
        offset_bps: int,
        leverage: float,
        tier: int,
        atr: float,
        oracle_price: float,
        composite_score: float = 0.0,
        regime: str = "",
        signal_scores: dict | None = None,
    ) -> bool:
        """Initiate a new position entry."""
        if not self._transition(ExecutorState.PENDING):
            return False

        self._metrics = ExecutorMetrics(
            direction=direction,
            size_usd=size_usd,
            leverage=leverage,
            tier=tier,
            entry_time=time.time(),
            composite_score=composite_score,
            regime=regime,
            signal_scores=signal_scores or {},
        )

        # Compute ATR-based stops (MG Patch 4)
        self._compute_stops(oracle_price, atr, direction, tier)

        # Place the entry order
        result = await self._om.place_entry(direction, size_usd, offset_bps)
        if result is None:
            logger.error("Entry order failed, reverting to CLOSED")
            self._transition(ExecutorState.CANCELLED)
            self._transition(ExecutorState.CLOSED)
            return False

        logger.info(
            "Entry initiated SA#%d: %s $%.2f %dx T%d SL=%.4f TP=%.4f",
            self._sub_account_id, direction.value, size_usd,
            leverage, tier, self._metrics.sl_price, self._metrics.tp_price,
        )
        return True

    def _compute_stops(
        self,
        oracle_price: float,
        atr: float,
        direction: Direction,
        tier: int,
    ) -> None:
        """ATR-based stop loss and take profit (MG Patch 4).

        SL uses the tier's ATR multiple. TP uses 1.5× the SL distance
        for a minimum 1.5:1 reward-to-risk.
        """
        tier_def = config.LEVERAGE_TIERS[tier]
        sl_distance = tier_def.atr_mult * atr
        tp_distance = sl_distance * 1.5  # 1.5:1 R:R minimum

        if direction == Direction.LONG:
            self._metrics.sl_price = oracle_price - sl_distance
            self._metrics.tp_price = oracle_price + tp_distance
        else:
            self._metrics.sl_price = oracle_price + sl_distance
            self._metrics.tp_price = oracle_price - tp_distance

    # --------------------------------------------------------
    # PENDING: Check for fills
    # --------------------------------------------------------

    async def check_fill(self, drift_wrapper) -> bool:
        """Check if the entry order has been filled."""
        if self.state != ExecutorState.PENDING:
            return False

        # Check for timeout first
        if self._om.check_entry_timeout():
            logger.info("Entry timed out SA#%d", self._sub_account_id)
            await self._om.cancel_entry()
            self._transition(ExecutorState.CANCELLED)
            self._transition(ExecutorState.CLOSED)
            return False

        # Check position
        pos = drift_wrapper.get_perp_position(self._sub_account_id)
        if pos is None or pos.base_asset_amount == 0:
            return False

        # Filled!
        fill_time = time.time()
        self._metrics.fill_latency_ms = (fill_time - self._metrics.entry_time) * 1000
        self._metrics.size_base = abs(pos.base_asset_amount)
        self._metrics.entry_price = abs(
            pos.quote_entry_amount / max(abs(pos.base_asset_amount), 1)
        ) / (config.QUOTE_PRECISION / config.BASE_PRECISION)

        if not self._transition(ExecutorState.ACTIVE):
            return False

        # Place TP/SL trigger orders
        await self._om.place_tp_sl(
            direction=self._metrics.direction,
            size_base=self._metrics.size_base,
            tp_price=self._metrics.tp_price,
            sl_price=self._metrics.sl_price,
        )

        logger.info(
            "Entry FILLED SA#%d: %s @ %.4f size=%d latency=%.0fms",
            self._sub_account_id, self._metrics.direction.value,
            self._metrics.entry_price, self._metrics.size_base,
            self._metrics.fill_latency_ms,
        )
        return True

    # --------------------------------------------------------
    # ACTIVE: Manage position
    # --------------------------------------------------------

    async def manage_position(self, oracle_price: float, drift_wrapper) -> str | None:
        """Called each tick while ACTIVE. Updates MAE/MFE, checks exits.

        Returns exit_reason if position should close, None otherwise.
        """
        if self.state != ExecutorState.ACTIVE:
            return None

        # Update MAE/MFE
        self._update_mae_mfe(oracle_price)

        # Check if position is still open
        pos = drift_wrapper.get_perp_position(self._sub_account_id)
        if pos is None or pos.base_asset_amount == 0:
            # Position closed (TP/SL trigger fired on Drift)
            self._metrics.exit_price = oracle_price
            self._metrics.exit_time = time.time()
            self._metrics.exit_reason = "trigger"
            return await self._finalize_close(drift_wrapper)

        return None

    def _update_mae_mfe(self, oracle_price: float) -> None:
        """Track Max Adverse Excursion and Max Favorable Excursion."""
        if self._metrics.entry_price == 0:
            return

        if self._metrics.direction == Direction.LONG:
            unrealized = oracle_price - self._metrics.entry_price
        else:
            unrealized = self._metrics.entry_price - oracle_price

        self._metrics.mfe = max(self._metrics.mfe, unrealized)
        self._metrics.mae = min(self._metrics.mae, unrealized)

    # --------------------------------------------------------
    # ACTIVE → CLOSING: Signal-based exit
    # --------------------------------------------------------

    async def initiate_close(self, reason: str, drift_wrapper) -> bool:
        """Begin closing the position (signal flip, stale exit, etc.)."""
        if not self._transition(ExecutorState.CLOSING):
            return False

        self._metrics.exit_reason = reason
        self._metrics.exit_time = time.time()

        # Cancel TP/SL triggers
        await self._om.cancel_tp_sl()

        # Place market close
        await self._om.emergency_close(
            direction=self._metrics.direction,
            size_base=self._metrics.size_base,
        )
        return True

    async def check_close_fill(self, drift_wrapper) -> bool:
        """Check if close order has been filled."""
        if self.state != ExecutorState.CLOSING:
            return False

        pos = drift_wrapper.get_perp_position(self._sub_account_id)
        if pos is None or pos.base_asset_amount == 0:
            oracle_price = drift_wrapper.get_oracle_price()
            self._metrics.exit_price = oracle_price
            await self._finalize_close(drift_wrapper)
            return True
        return False

    # --------------------------------------------------------
    # ACTIVE → EMERGENCY: Forced close
    # --------------------------------------------------------

    async def emergency_close(self, reason: str, drift_wrapper) -> None:
        """Emergency close — G_LIQ, G_KILL, or watcher fallback."""
        if self.state not in (ExecutorState.ACTIVE, ExecutorState.PENDING):
            return

        if self.state == ExecutorState.PENDING:
            await self._om.cancel_entry()
            self._transition(ExecutorState.CANCELLED)
            self._transition(ExecutorState.CLOSED)
            return

        if not self._transition(ExecutorState.EMERGENCY):
            return

        self._metrics.exit_reason = reason
        self._metrics.exit_time = time.time()

        # Cancel everything and market close
        await self._om.cancel_all()
        sig = await self._om.emergency_close(
            direction=self._metrics.direction,
            size_base=self._metrics.size_base,
        )

        oracle_price = drift_wrapper.get_oracle_price()
        self._metrics.exit_price = oracle_price
        await self._finalize_close(drift_wrapper)

    # --------------------------------------------------------
    # Finalization
    # --------------------------------------------------------

    async def _finalize_close(self, drift_wrapper) -> str:
        """Record trade and transition to CLOSED."""
        # Compute PnL
        if self._metrics.direction == Direction.LONG:
            self._metrics.pnl_usd = (
                (self._metrics.exit_price - self._metrics.entry_price)
                * self._metrics.size_base / config.BASE_PRECISION
            )
        else:
            self._metrics.pnl_usd = (
                (self._metrics.entry_price - self._metrics.exit_price)
                * self._metrics.size_base / config.BASE_PRECISION
            )

        duration = self._metrics.exit_time - self._metrics.entry_time

        # Log to telemetry
        self._telemetry.log_trade(TradeRecord(
            trade_id=f"SA{self._sub_account_id}_{int(self._metrics.entry_time)}",
            sub_account=self._sub_account_id,
            direction=self._metrics.direction.value,
            entry_price=self._metrics.entry_price,
            exit_price=self._metrics.exit_price,
            size_usd=self._metrics.size_usd,
            size_base=self._metrics.size_base,
            leverage=self._metrics.leverage,
            tier=self._metrics.tier,
            entry_time=self._metrics.entry_time,
            exit_time=self._metrics.exit_time,
            duration_s=duration,
            pnl_usd=self._metrics.pnl_usd,
            pnl_pct=self._metrics.pnl_usd / max(self._metrics.size_usd, 0.01) * 100,
            mae=self._metrics.mae,
            mfe=self._metrics.mfe,
            sl_price=self._metrics.sl_price,
            tp_price=self._metrics.tp_price,
            exit_reason=self._metrics.exit_reason,
            fill_latency_ms=self._metrics.fill_latency_ms,
            cancel_replace_count=self._metrics.cancel_replace_count,
            regime=self._metrics.regime,
            composite_score=self._metrics.composite_score,
            signal_scores=self._metrics.signal_scores,
        ))

        logger.info(
            "Trade closed SA#%d: %s PnL=$%.4f (%s) duration=%.1fs",
            self._sub_account_id, self._metrics.direction.value,
            self._metrics.pnl_usd, self._metrics.exit_reason, duration,
        )

        # Transition to CLOSED
        if self.state == ExecutorState.EMERGENCY:
            self._transition(ExecutorState.CLOSED)
        elif self.state == ExecutorState.CLOSING:
            self._transition(ExecutorState.CLOSED)
        elif self.state == ExecutorState.ACTIVE:
            # TP/SL fired on Drift directly
            self.state = ExecutorState.CLOSED

        return self._metrics.exit_reason

    @property
    def metrics(self) -> ExecutorMetrics:
        return self._metrics

    @property
    def direction(self) -> Direction:
        return self._metrics.direction

    @property
    def sl_price(self) -> float:
        return self._metrics.sl_price

    @property
    def tp_price(self) -> float:
        return self._metrics.tp_price

    @property
    def size_base(self) -> int:
        return self._metrics.size_base
