"""
Risk Gate Manager — 8 deterministic gates with strict precedence.

Gates are evaluated P0 (highest) to P7 (lowest). Evaluation short-circuits
on the first blocking gate. Each gate returns pass/fail with reason.

Implements:
- MG Patch 2: G_LIQ hysteresis (trigger < 2.0, clear > 2.3)
- MG Patch 3: Funding gate hold-time estimator
- Edge Case A: Re-entry cooldowns after forced exits
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from warpath import config
from warpath.config import (
    DegradedMode,
    Direction,
    GateID,
    GateResult,
    GATE_PRECEDENCE,
)

logger = logging.getLogger(__name__)


@dataclass
class GateState:
    """Mutable state tracked across ticks for stateful gates."""

    # G_LIQ hysteresis (MG Patch 2)
    g_liq_active: bool = False

    # G_DD high-water mark
    session_hwm: float = 0.0

    # G_DAY daily tracking
    daily_realized_pnl: float = 0.0
    daily_reset_ts: float = field(default_factory=time.time)

    # G_CONSEC
    consecutive_losses: int = 0

    # G_VOL pause
    vol_pause_until: float = 0.0

    # G_RPC
    rpc_healthy: bool = True

    # Kill switch
    kill_active: bool = False

    # Cooldowns (Edge Case A)
    cooldowns: dict[str, float] = field(default_factory=dict)
    # Keys: "sl:{market}:{direction}", "liq:{market}", "consec"
    # Values: epoch timestamp when cooldown expires


class GateManager:
    """Evaluates all 8 risk gates in precedence order."""

    def __init__(self) -> None:
        self.state = GateState()

    def evaluate(
        self,
        drift_wrapper,
        oracle_price: float,
        funding_rate: float = 0.0,
        direction: Direction = Direction.NEUTRAL,
        tier: int = 1,
        current_nav: float = 0.0,
    ) -> GateResult:
        """Run all gates in precedence order. Short-circuits on first block.

        Returns GateResult with pass/fail, reason, sizing modifier, and mode.
        """
        now = time.time()

        # Check daily reset
        self._check_daily_reset(now)

        # Update HWM
        if current_nav > self.state.session_hwm:
            self.state.session_hwm = current_nav

        sizing_modifier = 1.0

        for gate_id in GATE_PRECEDENCE:
            result = self._evaluate_gate(
                gate_id, drift_wrapper, oracle_price,
                funding_rate, direction, tier, current_nav, now,
            )
            if not result.passed:
                logger.warning(
                    "Gate %s BLOCKED: %s (mode=%s)",
                    result.failed_gate, result.reason, result.mode.value,
                )
                return result

            # Accumulate sizing modifiers from passing gates (e.g. G_VOL)
            sizing_modifier *= result.sizing_modifier

        # Check cooldowns (Edge Case A)
        cooldown_key = self._cooldown_key(direction)
        if cooldown_key and cooldown_key in self.state.cooldowns:
            if now < self.state.cooldowns[cooldown_key]:
                remaining = self.state.cooldowns[cooldown_key] - now
                return GateResult(
                    passed=False,
                    failed_gate=GateID.G_CONSEC,
                    reason=f"Re-entry cooldown active ({remaining:.0f}s remaining)",
                    mode=DegradedMode.NORMAL,
                )

        return GateResult(passed=True, sizing_modifier=sizing_modifier)

    def _evaluate_gate(
        self,
        gate_id: GateID,
        drift_wrapper,
        oracle_price: float,
        funding_rate: float,
        direction: Direction,
        tier: int,
        current_nav: float,
        now: float,
    ) -> GateResult:
        """Evaluate a single gate. Returns GateResult."""

        if gate_id == GateID.G_KILL:
            return self._gate_kill()

        elif gate_id == GateID.G_LIQ:
            return self._gate_liq(drift_wrapper)

        elif gate_id == GateID.G_DD:
            return self._gate_dd(current_nav)

        elif gate_id == GateID.G_DAY:
            return self._gate_day(current_nav)

        elif gate_id == GateID.G_CONSEC:
            return self._gate_consec()

        elif gate_id == GateID.G_VOL:
            return self._gate_vol(now)

        elif gate_id == GateID.G_FUND:
            return self._gate_fund(funding_rate, direction, tier)

        elif gate_id == GateID.G_RPC:
            return self._gate_rpc(drift_wrapper)

        return GateResult(passed=True)

    # ============================================================
    # P0: G_KILL — Kill switch
    # ============================================================

    def _gate_kill(self) -> GateResult:
        if self.state.kill_active:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_KILL,
                reason="Kill switch active",
                mode=DegradedMode.FULL_HALT,
            )
        # Check kill file on disk
        if Path(config.KILL_FILE_PATH).exists():
            self.state.kill_active = True
            return GateResult(
                passed=False,
                failed_gate=GateID.G_KILL,
                reason="Kill file detected",
                mode=DegradedMode.FULL_HALT,
            )
        return GateResult(passed=True)

    def activate_kill(self) -> None:
        """Activate kill switch (from Telegram /kill)."""
        self.state.kill_active = True
        logger.critical("KILL SWITCH ACTIVATED")

    def deactivate_kill(self) -> None:
        """Deactivate kill switch (from Telegram /resume)."""
        self.state.kill_active = False
        # Also remove kill file if it exists
        kill_path = Path(config.KILL_FILE_PATH)
        if kill_path.exists():
            kill_path.unlink()
        logger.info("Kill switch deactivated")

    # ============================================================
    # P1: G_LIQ — Margin ratio with hysteresis (MG Patch 2)
    # ============================================================

    def _gate_liq(self, drift_wrapper) -> GateResult:
        try:
            margin_ratio = drift_wrapper.get_margin_ratio()
        except Exception as e:
            logger.error("G_LIQ: cannot read margin ratio: %s", e)
            return GateResult(
                passed=False,
                failed_gate=GateID.G_LIQ,
                reason=f"Margin ratio read failed: {e}",
                mode=DegradedMode.SAFE_MANAGE,
            )

        # Hysteresis logic (MG Patch 2)
        if margin_ratio < config.G_LIQ_TRIGGER:
            self.state.g_liq_active = True
        elif margin_ratio > config.G_LIQ_CLEAR:
            self.state.g_liq_active = False
        # Between trigger and clear: maintain current state

        if self.state.g_liq_active:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_LIQ,
                reason=f"Margin ratio {margin_ratio:.2f} < {config.G_LIQ_CLEAR:.1f} (hysteresis active)",
                mode=DegradedMode.SAFE_MANAGE,
            )
        return GateResult(passed=True)

    # ============================================================
    # P2: G_DD — Max drawdown from session peak
    # ============================================================

    def _gate_dd(self, current_nav: float) -> GateResult:
        if self.state.session_hwm <= 0:
            return GateResult(passed=True)

        drawdown = (self.state.session_hwm - current_nav) / self.state.session_hwm
        if drawdown > config.G_DD_THRESHOLD:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_DD,
                reason=f"Drawdown {drawdown:.1%} exceeds {config.G_DD_THRESHOLD:.0%}",
                mode=DegradedMode.SAFE_MANAGE,
            )
        return GateResult(passed=True)

    # ============================================================
    # P3: G_DAY — Daily loss limit
    # ============================================================

    def _gate_day(self, current_nav: float) -> GateResult:
        # Use daily PnL tracking
        daily_loss_pct = abs(self.state.daily_realized_pnl) / max(current_nav, 0.01)
        if self.state.daily_realized_pnl < 0 and daily_loss_pct > config.G_DAY_LIMIT:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_DAY,
                reason=f"Daily loss {daily_loss_pct:.1%} exceeds {config.G_DAY_LIMIT:.0%}",
                mode=DegradedMode.NORMAL,  # Block entries but don't degrade
            )
        return GateResult(passed=True)

    # ============================================================
    # P4: G_CONSEC — Consecutive losses
    # ============================================================

    def _gate_consec(self) -> GateResult:
        if self.state.consecutive_losses >= config.G_CONSEC_COUNT:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_CONSEC,
                reason=f"{self.state.consecutive_losses} consecutive losses",
                mode=DegradedMode.NORMAL,
            )
        return GateResult(passed=True)

    # ============================================================
    # P5: G_VOL — Volatility spike (MAD z-score)
    # ============================================================

    def _gate_vol(self, now: float) -> GateResult:
        if now < self.state.vol_pause_until:
            remaining = self.state.vol_pause_until - now
            return GateResult(
                passed=True,  # Pass but with sizing modifier
                sizing_modifier=0.5,
                reason=f"G_VOL pause ({remaining:.0f}s remaining), sizing 0.5x",
            )
        return GateResult(passed=True)

    def trigger_vol_pause(self, now: float | None = None) -> None:
        """Called by signal engine when MAD z-score exceeds threshold."""
        ts = now or time.time()
        self.state.vol_pause_until = ts + config.G_VOL_PAUSE
        logger.warning("G_VOL triggered: pausing for %ds", config.G_VOL_PAUSE)

    # ============================================================
    # P6: G_FUND — Funding rate gate (MG Patch 3)
    # ============================================================

    def _gate_fund(
        self, funding_rate: float, direction: Direction, tier: int,
    ) -> GateResult:
        if direction == Direction.NEUTRAL:
            return GateResult(passed=True)

        # Adverse = paying funding in our direction
        # LONG pays when funding > 0, SHORT pays when funding < 0
        is_adverse = (
            (direction == Direction.LONG and funding_rate > 0)
            or (direction == Direction.SHORT and funding_rate < 0)
        )

        if not is_adverse:
            return GateResult(passed=True)

        abs_rate = abs(funding_rate)
        hold_hours = config.EXPECTED_HOLD_HOURS.get(config.CANDLE_TIMEFRAME, 2.0)
        # Funding is per 8hr, scale to hold time
        expected_funding_cost = abs_rate * (hold_hours / 8.0)

        if abs_rate >= config.G_FUND_BLOCK_HIGH:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_FUND,
                reason=f"Funding {abs_rate:.4%}/8hr too high for any entry",
                mode=DegradedMode.NORMAL,
            )

        if abs_rate >= config.G_FUND_REQUIRE_T3 and tier < 3:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_FUND,
                reason=f"Funding {abs_rate:.4%}/8hr requires Tier 3 (have Tier {tier})",
                mode=DegradedMode.NORMAL,
            )

        if abs_rate >= config.G_FUND_REQUIRE_T2 and tier < 2:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_FUND,
                reason=f"Funding {abs_rate:.4%}/8hr requires Tier 2+ (have Tier {tier})",
                mode=DegradedMode.NORMAL,
            )

        return GateResult(passed=True)

    # ============================================================
    # P7: G_RPC — Connection health
    # ============================================================

    def _gate_rpc(self, drift_wrapper) -> GateResult:
        if not drift_wrapper.is_connected:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_RPC,
                reason="Drift client disconnected",
                mode=DegradedMode.FULL_HALT,
            )

        age = drift_wrapper.rpc_age_s
        if age > config.G_RPC_DISCONNECT_MAX:
            return GateResult(
                passed=False,
                failed_gate=GateID.G_RPC,
                reason=f"RPC stale for {age:.1f}s (max {config.G_RPC_DISCONNECT_MAX}s)",
                mode=DegradedMode.SAFE_MANAGE,
            )

        return GateResult(passed=True)

    # ============================================================
    # State updates (called by executor on trade completion)
    # ============================================================

    def record_trade_result(self, pnl: float, direction: Direction, exit_reason: str) -> None:
        """Update gate state after a trade closes."""
        self.state.daily_realized_pnl += pnl

        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

        # Set cooldowns (Edge Case A)
        now = time.time()
        if exit_reason == "sl":
            key = f"sl:{config.PERP_MARKET_INDEX}:{direction.value}"
            self.state.cooldowns[key] = now + config.COOLDOWN_AFTER_SL
            logger.info("Cooldown set: %s for %ds", key, config.COOLDOWN_AFTER_SL)

        elif exit_reason == "liq":
            key = f"liq:{config.PERP_MARKET_INDEX}"
            self.state.cooldowns[key] = now + config.COOLDOWN_AFTER_LIQ
            logger.info("Cooldown set: %s for %ds", key, config.COOLDOWN_AFTER_LIQ)

        if self.state.consecutive_losses >= config.G_CONSEC_COUNT:
            key = "consec"
            self.state.cooldowns[key] = now + config.COOLDOWN_AFTER_CONSEC
            logger.info("Cooldown set: consec for %ds", config.COOLDOWN_AFTER_CONSEC)

    def _cooldown_key(self, direction: Direction) -> str | None:
        """Get the most relevant cooldown key for a potential entry."""
        now = time.time()
        keys_to_check = [
            "consec",
            f"liq:{config.PERP_MARKET_INDEX}",
            f"sl:{config.PERP_MARKET_INDEX}:{direction.value}",
        ]
        for key in keys_to_check:
            if key in self.state.cooldowns and now < self.state.cooldowns[key]:
                return key
        return None

    def _check_daily_reset(self, now: float) -> None:
        """Reset daily counters at UTC midnight."""
        import datetime
        today_start = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).timestamp()

        if self.state.daily_reset_ts < today_start:
            self.state.daily_realized_pnl = 0.0
            self.state.daily_reset_ts = now
            logger.info("Daily counters reset")
