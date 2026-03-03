"""
Telemetry — structured JSONL logging for trades, signals, gates, and heartbeats.

Flush interval: every 60s or on position close (MG Patch 1).
Files: trades.jsonl, signals.jsonl, gates.jsonl, heartbeat.jsonl
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from warpath import config

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str = ""
    sub_account: int = 0
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    size_usd: float = 0.0
    size_base: int = 0
    leverage: float = 0.0
    tier: int = 0
    entry_time: float = 0.0
    exit_time: float = 0.0
    duration_s: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    mae: float = 0.0        # Max Adverse Excursion (worst unrealized loss)
    mfe: float = 0.0        # Max Favorable Excursion (best unrealized profit)
    sl_price: float = 0.0
    tp_price: float = 0.0
    exit_reason: str = ""    # tp, sl, signal_flip, emergency, kill
    slippage_bps: float = 0.0
    fill_latency_ms: float = 0.0
    cancel_replace_count: int = 0
    fees_usd: float = 0.0
    regime: str = ""
    composite_score: float = 0.0
    signal_scores: dict = field(default_factory=dict)
    gate_states: dict = field(default_factory=dict)


@dataclass
class SignalRecord:
    timestamp: float = 0.0
    timeframe: str = ""
    regime: str = ""
    bb_score: float = 0.0
    sar_score: float = 0.0
    ha_score: float = 0.0
    dt_score: float = 0.0
    composite: float = 0.0
    direction: str = ""
    tier: int = 0
    oracle_price: float = 0.0
    atr: float = 0.0
    adx: float = 0.0
    bb_bandwidth: float = 0.0


@dataclass
class GateRecord:
    timestamp: float = 0.0
    gate_id: str = ""
    triggered: bool = False
    value: float = 0.0
    threshold: float = 0.0
    action: str = ""
    mode: str = ""


class Telemetry:
    """Append-only JSONL logger for all bot activity."""

    def __init__(self) -> None:
        self._dir = config.TELEMETRY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._last_flush = time.time()
        self._buffers: dict[str, list[dict]] = {
            "trades": [],
            "signals": [],
            "gates": [],
            "heartbeat": [],
        }
        logger.info("Telemetry initialized: %s", self._dir)

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.jsonl"

    def _append(self, name: str, record: dict) -> None:
        record["_ts"] = time.time()
        self._buffers[name].append(record)

    def flush(self, force: bool = False) -> None:
        """Write buffered records to disk."""
        now = time.time()
        if not force and (now - self._last_flush) < config.TELEMETRY_FLUSH_S:
            return

        for name, buf in self._buffers.items():
            if not buf:
                continue
            path = self._path(name)
            with open(path, "a") as f:
                for record in buf:
                    f.write(json.dumps(record, default=str) + "\n")
            buf.clear()

        self._last_flush = now

    def log_trade(self, record: TradeRecord) -> None:
        self._append("trades", asdict(record))
        self.flush(force=True)  # Always flush on trade close

    def log_signal(self, record: SignalRecord) -> None:
        self._append("signals", asdict(record))

    def log_gate(self, record: GateRecord) -> None:
        self._append("gates", asdict(record))

    def log_heartbeat(self, data: dict) -> None:
        self._append("heartbeat", data)

    def heartbeat(self, drift_wrapper=None) -> None:
        """Periodic health check log entry."""
        hb = {
            "uptime_s": time.time(),
            "dry_run": config.DRY_RUN,
            "market": config.PERP_MARKET_INDEX,
        }
        if drift_wrapper and drift_wrapper.is_connected:
            try:
                hb["oracle_price"] = drift_wrapper.get_oracle_price()
                hb["nav"] = drift_wrapper.get_nav()
                hb["free_collateral"] = drift_wrapper.get_free_collateral()
                hb["margin_ratio"] = drift_wrapper.get_margin_ratio()
            except Exception as e:
                hb["error"] = str(e)
        self.log_heartbeat(hb)
        self.flush()
