"""
Telegram bot — alerts and commands for WARPATH.

Commands: /status, /kill, /resume, /pnl, /positions, /signals, /gates
Push alerts: entries, exits, gate trips, mode changes, heartbeats.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from warpath import config

if TYPE_CHECKING:
    from warpath.execution.drift_client import DriftWrapper

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram interface for monitoring and kill switch."""

    def __init__(self) -> None:
        self._token = config.TELEGRAM_BOT_TOKEN
        self._chat_id = config.TELEGRAM_CHAT_ID
        self._app = None
        self._kill_callback = None
        self._resume_callback = None
        self._drift: DriftWrapper | None = None
        self._start_time = time.time()
        self._enabled = bool(self._token and self._chat_id)

        if not self._enabled:
            logger.warning("Telegram not configured — bot alerts disabled")

    def set_drift(self, drift: DriftWrapper) -> None:
        self._drift = drift

    def set_kill_callback(self, cb) -> None:
        self._kill_callback = cb

    def set_resume_callback(self, cb) -> None:
        self._resume_callback = cb

    async def start(self) -> None:
        """Initialize the Telegram bot with command handlers."""
        if not self._enabled:
            return

        try:
            from telegram import Update
            from telegram.ext import (
                ApplicationBuilder,
                CommandHandler,
                ContextTypes,
            )

            self._app = (
                ApplicationBuilder()
                .token(self._token)
                .build()
            )

            async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text(self._format_status())

            async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if self._kill_callback:
                    await self._kill_callback()
                await update.message.reply_text("KILL SWITCH ACTIVATED. FULL_HALT mode.")

            async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if self._resume_callback:
                    await self._resume_callback()
                await update.message.reply_text("Resume requested. Returning to NORMAL mode.")

            async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text(self._format_pnl())

            async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text(self._format_positions())

            self._app.add_handler(CommandHandler("status", cmd_status))
            self._app.add_handler(CommandHandler("kill", cmd_kill))
            self._app.add_handler(CommandHandler("resume", cmd_resume))
            self._app.add_handler(CommandHandler("pnl", cmd_pnl))
            self._app.add_handler(CommandHandler("positions", cmd_positions))

            await self._app.initialize()
            await self._app.start()
            if self._app.updater:
                await self._app.updater.start_polling(drop_pending_updates=True)

            logger.info("Telegram bot started")
        except ImportError:
            logger.warning("python-telegram-bot not installed — Telegram disabled")
            self._enabled = False
        except Exception as e:
            logger.error("Telegram init failed: %s", e)
            self._enabled = False

    async def stop(self) -> None:
        if self._app:
            try:
                if self._app.updater:
                    await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.warning("Telegram shutdown error: %s", e)

    # --------------------------------------------------------
    # Push alerts
    # --------------------------------------------------------

    async def send(self, message: str) -> None:
        """Send a push alert to the configured chat."""
        if not self._enabled:
            logger.info("[TG] %s", message)
            return
        try:
            from telegram import Bot

            bot = Bot(token=self._token)
            await bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Telegram send failed: %s", e)

    async def alert_entry(
        self, direction: str, price: float, size_usd: float,
        leverage: float, tier: int, score: float,
    ) -> None:
        msg = (
            f"*ENTRY* {'🟢' if direction == 'LONG' else '🔴'}\n"
            f"Direction: {direction}\n"
            f"Price: ${price:,.4f}\n"
            f"Size: ${size_usd:.2f} ({leverage:.0f}x)\n"
            f"Tier: {tier} | Score: {score:.3f}\n"
            f"Mode: {'DRY_RUN' if config.DRY_RUN else 'LIVE'}"
        )
        await self.send(msg)

    async def alert_exit(
        self, direction: str, entry_price: float, exit_price: float,
        pnl: float, reason: str,
    ) -> None:
        msg = (
            f"*EXIT* {'✅' if pnl >= 0 else '❌'}\n"
            f"Direction: {direction}\n"
            f"Entry: ${entry_price:,.4f} → Exit: ${exit_price:,.4f}\n"
            f"PnL: ${pnl:+.4f} ({reason})"
        )
        await self.send(msg)

    async def alert_gate(self, gate_id: str, reason: str, mode: str) -> None:
        msg = f"*GATE TRIP* ⚠️\nGate: {gate_id}\nReason: {reason}\nMode: {mode}"
        await self.send(msg)

    async def alert_mode_change(self, old_mode: str, new_mode: str, reason: str) -> None:
        msg = f"*MODE CHANGE*\n{old_mode} → {new_mode}\nReason: {reason}"
        await self.send(msg)

    # --------------------------------------------------------
    # Formatters
    # --------------------------------------------------------

    def _format_status(self) -> str:
        uptime = time.time() - self._start_time
        hours = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)

        lines = [
            f"*WARPATH Status*",
            f"Uptime: {hours}h {mins}m",
            f"Mode: {'DRY_RUN' if config.DRY_RUN else 'LIVE'}",
            f"Market: SOL-PERP (index {config.PERP_MARKET_INDEX})",
            f"Timeframe: {config.CANDLE_TIMEFRAME}",
        ]

        if self._drift and self._drift.is_connected:
            try:
                lines.append(f"Oracle: ${self._drift.get_oracle_price():,.4f}")
                lines.append(f"NAV: ${self._drift.get_nav():,.2f}")
                lines.append(f"Free Collateral: ${self._drift.get_free_collateral():,.2f}")
                lines.append(f"Margin Ratio: {self._drift.get_margin_ratio():.2f}")
            except Exception as e:
                lines.append(f"Data error: {e}")
        else:
            lines.append("Connection: DISCONNECTED")

        return "\n".join(lines)

    def _format_pnl(self) -> str:
        if not self._drift or not self._drift.is_connected:
            return "Not connected"
        try:
            unrealized = self._drift.get_unrealized_pnl()
            nav = self._drift.get_nav()
            return (
                f"*PnL Report*\n"
                f"NAV: ${nav:,.2f}\n"
                f"Unrealized: ${unrealized:+,.4f}"
            )
        except Exception as e:
            return f"PnL error: {e}"

    def _format_positions(self) -> str:
        if not self._drift or not self._drift.is_connected:
            return "Not connected"
        try:
            pos = self._drift.get_perp_position()
            if pos is None:
                return "No open positions"
            base = pos.base_asset_amount / config.BASE_PRECISION
            direction = "LONG" if pos.base_asset_amount > 0 else "SHORT"
            return (
                f"*Position*\n"
                f"Direction: {direction}\n"
                f"Size: {abs(base):.6f} SOL\n"
                f"Entry: ${pos.quote_entry_amount / config.QUOTE_PRECISION:,.4f}"
            )
        except Exception as e:
            return f"Position error: {e}"
