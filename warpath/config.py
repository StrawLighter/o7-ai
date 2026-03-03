"""
WARPATH Configuration — Single source of truth.

All constants from WARPATH Spec v0.2 + MG Patches 1-7 + Edge Cases A/B.
Every value can be overridden via environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_bool(key: str, default: bool) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


def _env_int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(_env(key, str(default)))


# ============================================================
# Enums
# ============================================================


class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class Regime(Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    VOLATILE = "VOLATILE"
    TRANSITIONAL = "TRANSITIONAL"


class ExecutorState(Enum):
    CLOSED = "CLOSED"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    EMERGENCY = "EMERGENCY"
    CANCELLED = "CANCELLED"


class DegradedMode(Enum):
    NORMAL = "NORMAL"
    SAFE_MANAGE = "SAFE_MANAGE"
    FULL_HALT = "FULL_HALT"


class GateID(Enum):
    G_KILL = "G_KILL"
    G_LIQ = "G_LIQ"
    G_DD = "G_DD"
    G_DAY = "G_DAY"
    G_CONSEC = "G_CONSEC"
    G_VOL = "G_VOL"
    G_FUND = "G_FUND"
    G_RPC = "G_RPC"


# Gate precedence (lower index = higher priority)
GATE_PRECEDENCE: list[GateID] = [
    GateID.G_KILL,    # P0
    GateID.G_LIQ,     # P1
    GateID.G_DD,      # P2
    GateID.G_DAY,     # P3
    GateID.G_CONSEC,  # P4
    GateID.G_VOL,     # P5
    GateID.G_FUND,    # P6
    GateID.G_RPC,     # P7
]


# ============================================================
# Data classes
# ============================================================


@dataclass(frozen=True)
class LeverageTier:
    tier: int
    base_leverage: float
    entry_offset_bps: int
    entry_timeout_s: int
    atr_mult: float
    signal_min: float  # minimum |composite_score| to qualify


@dataclass
class GateResult:
    passed: bool
    failed_gate: GateID | None = None
    reason: str | None = None
    sizing_modifier: float = 1.0
    mode: DegradedMode = DegradedMode.NORMAL


# ============================================================
# Solana / Drift
# ============================================================

RPC_URL_PRIMARY: str = _env("RPC_URL_PRIMARY", "https://api.devnet.solana.com")
RPC_URL_SECONDARY: str = _env("RPC_URL_SECONDARY", "https://api.devnet.solana.com")
PRIVATE_KEY: str = _env("PRIVATE_KEY", "")
KEYPAIR_PATH: str = _env("KEYPAIR_PATH", "")

DRIFT_ENV: str = _env("DRIFT_ENV", "devnet")
PERP_MARKET_INDEX: int = _env_int("DRIFT_MARKET_INDEX", 0)  # SOL-PERP
SPOT_MARKET_INDEX: int = 0  # USDC — always required by driftpy
SUB_ACCOUNT_ID: int = _env_int("DRIFT_SUB_ACCOUNT_ID", 0)

# Drift precision constants
PRICE_PRECISION: int = 1_000_000
BASE_PRECISION: int = 1_000_000_000
QUOTE_PRECISION: int = 1_000_000


# ============================================================
# Safety flags
# ============================================================

WARPATH_LIVE: bool = _env_bool("WARPATH_LIVE", False)
WARPATH_CONFIRM: bool = _env_bool("WARPATH_CONFIRM", False)
DRY_RUN: bool = not (WARPATH_LIVE and WARPATH_CONFIRM)


# ============================================================
# MG Patch 1 — Tick Cadence
# ============================================================

TICK_MODE: str = "hybrid"  # ws_or_timer
TICK_TIMER_MS: int = _env_int("WARPATH_TICK_MS", 500)
WATCHER_INTERVAL_MS: int = 1000
TELEMETRY_FLUSH_S: int = 60


# ============================================================
# Candle / Data
# ============================================================

CANDLE_TIMEFRAME: str = _env("WARPATH_TIMEFRAME", "5m")

# Minimum candle history required for indicators
MIN_CANDLES_BB: int = 20
MIN_CANDLES_ATR: int = 14
MIN_CANDLES_ADX: int = 14
MIN_CANDLES_SAR: int = 5
MIN_CANDLES_WARMUP: int = 25  # max of the above + buffer

# Timeframe durations in seconds
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}


# ============================================================
# Signal Weights (default: Transitional regime)
# ============================================================

W_BB: float = 0.30
W_SAR: float = 0.25
W_HA: float = 0.25
W_DT: float = 0.20

# Regime weight overrides: regime -> {signal: weight}
REGIME_WEIGHTS: dict[Regime, dict[str, float]] = {
    Regime.TREND: {"bb": 0.20, "sar": 0.30, "ha": 0.30, "dt": 0.20},
    Regime.RANGE: {"bb": 0.40, "sar": 0.20, "ha": 0.20, "dt": 0.20},
    Regime.VOLATILE: {"bb": 0.25, "sar": 0.25, "ha": 0.25, "dt": 0.25},
    Regime.TRANSITIONAL: {"bb": W_BB, "sar": W_SAR, "ha": W_HA, "dt": W_DT},
}

# Regime classification thresholds
REGIME_ADX_TREND: float = 25.0
REGIME_ADX_RANGE: float = 20.0
REGIME_BW_RANGE: float = 0.04
REGIME_BW_TREND: float = 0.05
REGIME_BW_VOLATILE: float = 0.06
REGIME_MIN_DURATION: int = 5  # candles before switching regime


# ============================================================
# Composite thresholds → Tier mapping
# ============================================================

# |composite_score| thresholds for tier assignment
TIER_3_THRESHOLD: float = 0.75   # strong signal → highest leverage
TIER_2_THRESHOLD: float = 0.60   # moderate signal
TIER_1_THRESHOLD: float = 0.45   # weak signal → conservative

# Tier definitions: (base_leverage, offset_bps, timeout_s, atr_mult, min_score)
LEVERAGE_TIERS: dict[int, LeverageTier] = {
    1: LeverageTier(tier=1, base_leverage=12, entry_offset_bps=2, entry_timeout_s=60, atr_mult=2.0, signal_min=TIER_1_THRESHOLD),
    2: LeverageTier(tier=2, base_leverage=17, entry_offset_bps=3, entry_timeout_s=45, atr_mult=1.5, signal_min=TIER_2_THRESHOLD),
    3: LeverageTier(tier=3, base_leverage=22, entry_offset_bps=5, entry_timeout_s=30, atr_mult=1.0, signal_min=TIER_3_THRESHOLD),
}


# ============================================================
# Sizing
# ============================================================

USDC_PER_SUBACCOUNT: float = _env_float("USDC_PER_SUBACCOUNT", 10.0)
NAV_CEILING_PCT: float = _env_float("WARPATH_NAV_CEIL", 0.30)

# Regime coupling multipliers for effective leverage
REGIME_LEVERAGE_MULT: dict[Regime, float] = {
    Regime.TREND: 1.0,
    Regime.RANGE: 0.7,
    Regime.VOLATILE: 0.5,
    Regime.TRANSITIONAL: 0.85,
}

TARGET_DAILY_VOL: float = 0.02    # 2% daily for vol_cap
MAX_SPREAD_BPS: float = 15.0      # for spread_cap


# ============================================================
# MG Patch 2 — G_LIQ Margin Ratio Hysteresis
# ============================================================

G_LIQ_TRIGGER: float = 2.0
G_LIQ_CLEAR: float = 2.3


# ============================================================
# Risk Gate Thresholds (§5.3 from spec)
# ============================================================

G_DD_THRESHOLD: float = 0.15       # 15% drawdown from peak
G_DAY_LIMIT: float = 0.05          # 5% daily loss
G_CONSEC_COUNT: int = 3            # consecutive losses before block

G_VOL_ZSCORE: float = 4.0          # MAD-based z-score
G_VOL_WINDOW: int = 60             # minutes, rolling window
G_VOL_PAUSE: int = 300             # seconds to pause after trip

G_FUND_BLOCK_HIGH: float = 0.002   # 0.20% / 8hr — block all entries
G_FUND_REQUIRE_T3: float = 0.001   # 0.10% / 8hr — require Tier 3 signal
G_FUND_REQUIRE_T2: float = 0.0005  # 0.05% / 8hr — require Tier 2+ signal

G_RPC_LATENCY_MAX: int = 2000      # ms
G_RPC_DISCONNECT_MAX: int = 10     # seconds

KILL_FILE_PATH: str = str(Path(__file__).parent / "data" / "KILL")


# ============================================================
# MG Patch 3 — Funding Gate Hold-Time Estimator
# ============================================================

EXPECTED_HOLD_HOURS: dict[str, float] = {
    "1m": 0.5,
    "5m": 2.0,
    "15m": 6.0,
}


# ============================================================
# MG Patch 4 — Price-Based Stop Loss (ATR multiples per leverage)
# ============================================================

ATR_MULT_10X: float = 2.0
ATR_MULT_15X: float = 1.5
ATR_MULT_20X: float = 1.2
ATR_MULT_25X: float = 1.0


# ============================================================
# MG Patch 5 — Directional Oracle Limit Offsets
# ============================================================

ENTRY_OFFSET_T3: float = 0.0005    # 5bps
ENTRY_OFFSET_T2: float = 0.0003    # 3bps
ENTRY_OFFSET_T1: float = 0.0002    # 2bps


# ============================================================
# Execution Parameters (§5.4 from spec)
# ============================================================

ENTRY_TIMEOUT_T3: int = 30         # seconds
ENTRY_TIMEOUT_T2: int = 45
ENTRY_TIMEOUT_T1: int = 60
MAX_CANCEL_REPLACE: int = 3        # per signal
MAX_SLIPPAGE_ENTRY: int = 10       # bps, Tier 3
MAX_SLIPPAGE_EMERGENCY: int = 50   # bps, G_KILL/G_LIQ
WATCHER_TRIGGER_GRACE: int = 5     # seconds, SL fallback
WATCHER_TP_GRACE: int = 10         # seconds, TP fallback


# ============================================================
# Edge Case A — Re-Entry Cooldown
# ============================================================

COOLDOWN_AFTER_SL: int = 120       # seconds
COOLDOWN_AFTER_LIQ: int = 300      # seconds
COOLDOWN_AFTER_CONSEC: int = 3600  # seconds


# ============================================================
# Telegram
# ============================================================

TELEGRAM_BOT_TOKEN: str = _env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = _env("TELEGRAM_CHAT_ID", "")
TELEGRAM_HEARTBEAT_S: int = 900    # 15 minutes


# ============================================================
# Logging / Telemetry
# ============================================================

LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")
TELEMETRY_DIR: Path = Path(_env("TELEMETRY_DIR", str(Path(__file__).parent / "data" / "logs")))


# ============================================================
# Bollinger Bands
# ============================================================

BB_PERIOD: int = 20
BB_STD_DEV: float = 2.0


# ============================================================
# Parabolic SAR
# ============================================================

SAR_AF_START: float = 0.02
SAR_AF_STEP: float = 0.02
SAR_AF_MAX: float = 0.20


# ============================================================
# Dual Thrust
# ============================================================

DT_K1: float = 0.5
DT_K2: float = 0.5
DT_LOOKBACK: int = 4   # candles for range calculation


# ============================================================
# ATR / ADX
# ============================================================

ATR_PERIOD: int = 14
ADX_PERIOD: int = 14
