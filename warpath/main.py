"""
WARPATH Main Orchestrator — hybrid tick event loop.

MG Patch 1: Fires on whichever comes first:
  - WebSocket oracle price update
  - 500ms timer

Wires all subsystems: data → signals → risk → execution → monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time

from warpath import config
from warpath.data.candle_builder import CandleBuilder
from warpath.data.feed import OracleFeed
from warpath.execution.drift_client import DriftWrapper
from warpath.execution.executor import Executor
from warpath.execution.order_manager import OrderManager
from warpath.monitoring.telegram_bot import TelegramBot
from warpath.monitoring.telemetry import Telemetry, SignalRecord
from warpath.risk.degraded_mode import DegradedModeManager
from warpath.risk.gate_manager import GateManager
from warpath.risk.sizing import compute_size
from warpath.risk.watcher import LocalWatcher
from warpath.signals.composite import CompositeScorer
from warpath.config import DegradedMode, Direction, ExecutorState

logger = logging.getLogger(__name__)


class Warpath:
    """Main orchestrator — connects all WARPATH subsystems."""

    def __init__(self) -> None:
        # Core
        self.drift = DriftWrapper()
        self.feed = OracleFeed()
        self.candles = CandleBuilder()
        self.scorer = CompositeScorer()

        # Risk
        self.gates = GateManager()
        self.degraded = DegradedModeManager()
        self.watcher = LocalWatcher()

        # Execution (single sub-account for now)
        self.order_manager = OrderManager(self.drift, config.SUB_ACCOUNT_ID)
        self.telemetry = Telemetry()
        self.executor = Executor(self.order_manager, self.telemetry, config.SUB_ACCOUNT_ID)

        # Monitoring
        self.telegram = TelegramBot()

        # State
        self._running = False
        self._start_time = 0.0
        self._last_heartbeat = 0.0
        self._tick_count = 0

    async def start(self) -> None:
        """Initialize all subsystems and enter the main loop."""
        self._setup_logging()
        logger.info("=" * 60)
        logger.info("WARPATH starting — %s", "DRY_RUN" if config.DRY_RUN else "LIVE")
        logger.info("Market: SOL-PERP (index %d)", config.PERP_MARKET_INDEX)
        logger.info("Timeframe: %s | Tick: %dms", config.CANDLE_TIMEFRAME, config.TICK_TIMER_MS)
        logger.info("Sub-Account: %d | Capital: $%.2f", config.SUB_ACCOUNT_ID, config.USDC_PER_SUBACCOUNT)
        logger.info("=" * 60)

        # Initialize Drift connection
        await self.drift.initialize()

        # Start subsystems
        await self.feed.start(self.drift)
        await self.watcher.start(self.drift)
        self.telegram.set_drift(self.drift)
        self.telegram.set_kill_callback(self._on_kill)
        self.telegram.set_resume_callback(self._on_resume)
        await self.telegram.start()

        # Send startup alert
        await self.telegram.send(
            f"*WARPATH ONLINE*\n"
            f"Mode: {'DRY_RUN' if config.DRY_RUN else 'LIVE'}\n"
            f"Market: SOL-PERP\n"
            f"Capital: ${config.USDC_PER_SUBACCOUNT:.2f}"
        )

        self._running = True
        self._start_time = time.time()
        self._last_heartbeat = time.time()

        # Enter main loop
        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        except Exception as e:
            logger.critical("Main loop fatal error: %s", e, exc_info=True)
            await self.telegram.send(f"*FATAL ERROR*\n{e}")
        finally:
            await self._shutdown()

    async def _main_loop(self) -> None:
        """Hybrid tick loop (MG Patch 1).

        Fires on whichever comes first:
        - Oracle price update via WebSocket
        - Timer expiry (TICK_TIMER_MS)
        """
        tick_interval = config.TICK_TIMER_MS / 1000.0

        while self._running:
            try:
                # Hybrid tick: wait for price event OR timer
                tick = await self.feed.wait_for_tick(timeout=tick_interval)

                if tick is None:
                    continue

                self._tick_count += 1
                await self._process_tick(tick.price, tick.timestamp)

                # Periodic heartbeat
                now = time.time()
                if now - self._last_heartbeat > config.TELEGRAM_HEARTBEAT_S:
                    self.telemetry.heartbeat(self.drift)
                    self._last_heartbeat = now

                # Flush telemetry
                self.telemetry.flush()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Tick processing error: %s", e, exc_info=True)
                await asyncio.sleep(1.0)

    async def _process_tick(self, price: float, timestamp: float) -> None:
        """Process a single tick through the full pipeline."""

        # 1. Update candles
        closed_candles = self.candles.on_tick(price, timestamp)

        # 2. Check degraded mode — if FULL_HALT, skip everything
        if self.degraded.should_flatten:
            await self._handle_full_halt()
            return

        # 3. Wait for warmup
        if not self.candles.is_warm:
            return

        # 4. Get candles for the active timeframe
        candles = self.candles.get_candles(config.CANDLE_TIMEFRAME)
        if not candles:
            return

        # 5. Process based on executor state
        if self.executor.is_idle:
            await self._try_entry(candles, price)
        elif self.executor.state == ExecutorState.PENDING:
            await self.executor.check_fill(self.drift)
        elif self.executor.state == ExecutorState.ACTIVE:
            exit_reason = await self.executor.manage_position(price, self.drift)
            if exit_reason:
                await self._on_position_closed(exit_reason)
        elif self.executor.state == ExecutorState.CLOSING:
            closed = await self.executor.check_close_fill(self.drift)
            if closed:
                await self._on_position_closed(self.executor.metrics.exit_reason)

    async def _try_entry(self, candles: list, price: float) -> None:
        """Evaluate signals and attempt entry if conditions met."""

        # Check cooldown
        if self.executor.is_in_cooldown:
            return

        # Check degraded mode
        if not self.degraded.can_open_positions:
            return

        # Score signals
        signal = self.scorer.score(candles, oracle_price=price)

        # No entry if tier 0 (below threshold)
        if signal.tier == 0 or signal.direction == Direction.NEUTRAL:
            return

        # Log signal
        self.telemetry.log_signal(SignalRecord(
            timestamp=time.time(),
            timeframe=config.CANDLE_TIMEFRAME,
            regime=signal.regime.value,
            bb_score=signal.bb_score,
            sar_score=signal.sar_score,
            ha_score=signal.ha_score,
            dt_score=signal.dt_score,
            composite=signal.composite_score,
            direction=signal.direction.value,
            tier=signal.tier,
            oracle_price=price,
            atr=signal.atr,
            adx=signal.adx,
            bb_bandwidth=signal.bb_bandwidth,
        ))

        # Evaluate risk gates
        funding_rate = 0.0
        try:
            funding_rate = self.drift.get_funding_rate()
        except Exception:
            pass

        nav = 0.0
        try:
            nav = self.drift.get_nav()
        except Exception:
            pass

        gate_result = self.gates.evaluate(
            drift_wrapper=self.drift,
            oracle_price=price,
            funding_rate=funding_rate,
            direction=signal.direction,
            tier=signal.tier,
            current_nav=nav,
        )

        if not gate_result.passed:
            # Update degraded mode if gate requested it
            if gate_result.mode != DegradedMode.NORMAL:
                self.degraded.update_from_gate_result(gate_result.mode, gate_result.reason or "")
                await self.telegram.alert_gate(
                    gate_result.failed_gate.value if gate_result.failed_gate else "UNKNOWN",
                    gate_result.reason or "",
                    self.degraded.mode.value,
                )
            return

        # Compute position size
        free_collateral = 0.0
        try:
            free_collateral = self.drift.get_free_collateral()
        except Exception:
            return

        sizing = compute_size(
            free_collateral=free_collateral,
            signal_strength=signal.composite_score,
            direction=signal.direction,
            regime=signal.regime,
            gate_result=gate_result,
            oracle_price=price,
        )

        if sizing is None:
            return

        # Execute entry
        tier_def = config.LEVERAGE_TIERS[sizing.tier]
        entered = await self.executor.enter(
            direction=sizing.direction,
            size_usd=sizing.size_usd,
            offset_bps=sizing.offset_bps,
            leverage=sizing.leverage,
            tier=sizing.tier,
            atr=signal.atr,
            oracle_price=price,
            composite_score=signal.composite_score,
            regime=signal.regime.value,
            signal_scores={
                "bb": signal.bb_score,
                "sar": signal.sar_score,
                "ha": signal.ha_score,
                "dt": signal.dt_score,
            },
        )

        if entered:
            # Register with watcher
            self.watcher.register_position(
                sub_account_id=config.SUB_ACCOUNT_ID,
                direction=sizing.direction,
                size_base=int(sizing.size_usd / price * config.BASE_PRECISION),
                sl_price=self.executor.sl_price,
                tp_price=self.executor.tp_price,
            )

            await self.telegram.alert_entry(
                direction=sizing.direction.value,
                price=price,
                size_usd=sizing.size_usd,
                leverage=sizing.leverage,
                tier=sizing.tier,
                score=signal.composite_score,
            )

    async def _on_position_closed(self, exit_reason: str) -> None:
        """Handle post-close bookkeeping."""
        metrics = self.executor.metrics

        # Update gate state
        self.gates.record_trade_result(
            pnl=metrics.pnl_usd,
            direction=metrics.direction,
            exit_reason=exit_reason,
        )

        # Unregister from watcher
        self.watcher.unregister_position(config.SUB_ACCOUNT_ID)

        # Check degraded mode recovery
        self.degraded.check_recovery(all_gates_clear=True)

        # Telegram alert
        await self.telegram.alert_exit(
            direction=metrics.direction.value,
            entry_price=metrics.entry_price,
            exit_price=metrics.exit_price,
            pnl=metrics.pnl_usd,
            reason=exit_reason,
        )

    async def _handle_full_halt(self) -> None:
        """FULL_HALT: cancel all orders and flatten."""
        if self.executor.state in (ExecutorState.ACTIVE, ExecutorState.PENDING):
            await self.executor.emergency_close("full_halt", self.drift)
        await self.order_manager.cancel_all()

    # --------------------------------------------------------
    # Kill switch callbacks
    # --------------------------------------------------------

    async def _on_kill(self) -> None:
        """Telegram /kill handler."""
        self.gates.activate_kill()
        self.degraded.transition(DegradedMode.FULL_HALT, "Kill switch activated")
        await self._handle_full_halt()

    async def _on_resume(self) -> None:
        """Telegram /resume handler."""
        self.gates.deactivate_kill()
        self.degraded.manual_reset()

    # --------------------------------------------------------
    # Shutdown
    # --------------------------------------------------------

    async def _shutdown(self) -> None:
        """Graceful shutdown — cancel orders, stop subsystems."""
        logger.info("WARPATH shutting down...")
        self._running = False

        try:
            await self.order_manager.cancel_all()
        except Exception as e:
            logger.error("Shutdown cancel failed: %s", e)

        await self.watcher.stop()
        await self.feed.stop()
        await self.telegram.send("*WARPATH OFFLINE*")
        await self.telegram.stop()
        await self.drift.shutdown()

        self.telemetry.flush(force=True)
        logger.info("WARPATH shutdown complete")

    # --------------------------------------------------------
    # Logging setup
    # --------------------------------------------------------

    def _setup_logging(self) -> None:
        logging.basicConfig(
            level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(
                    config.TELEMETRY_DIR / "warpath.log",
                    mode="a",
                ),
            ],
        )


def main():
    """Entry point."""
    config.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

    bot = Warpath()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        bot._running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        loop.run_until_complete(bot.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
