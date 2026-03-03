"""
Technical indicators — shared by signal engine and risk gates.

All computations use numpy for vectorized operations on candle arrays.
Functions accept list[Candle] and return numpy arrays.
"""

from __future__ import annotations

import numpy as np

from warpath.data.candle_builder import Candle


def _closes(candles: list[Candle]) -> np.ndarray:
    return np.array([c.close for c in candles], dtype=np.float64)


def _highs(candles: list[Candle]) -> np.ndarray:
    return np.array([c.high for c in candles], dtype=np.float64)


def _lows(candles: list[Candle]) -> np.ndarray:
    return np.array([c.low for c in candles], dtype=np.float64)


def _opens(candles: list[Candle]) -> np.ndarray:
    return np.array([c.open for c in candles], dtype=np.float64)


# ============================================================
# ATR — Average True Range
# ============================================================


def compute_true_range(candles: list[Candle]) -> np.ndarray:
    """True Range for each candle (index 0 uses high-low only)."""
    highs = _highs(candles)
    lows = _lows(candles)
    closes = _closes(candles)

    n = len(candles)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]

    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    return tr


def compute_atr(candles: list[Candle], period: int = 14) -> np.ndarray:
    """ATR using Wilder's smoothing (EMA-like)."""
    tr = compute_true_range(candles)
    n = len(tr)
    atr = np.full(n, np.nan, dtype=np.float64)

    if n < period:
        return atr

    # Initial ATR = simple mean of first `period` TRs
    atr[period - 1] = np.mean(tr[:period])

    # Wilder's smoothing
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


# ============================================================
# ADX — Average Directional Index
# ============================================================


def compute_adx(candles: list[Candle], period: int = 14) -> np.ndarray:
    """ADX (Average Directional Index) using Wilder's smoothing."""
    highs = _highs(candles)
    lows = _lows(candles)
    closes = _closes(candles)
    n = len(candles)

    adx = np.full(n, np.nan, dtype=np.float64)
    if n < period * 2:
        return adx

    # +DM and -DM
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

    tr = compute_true_range(candles)

    # Wilder's smoothing for TR, +DM, -DM
    smooth_tr = np.zeros(n, dtype=np.float64)
    smooth_plus = np.zeros(n, dtype=np.float64)
    smooth_minus = np.zeros(n, dtype=np.float64)

    smooth_tr[period] = np.sum(tr[1 : period + 1])
    smooth_plus[period] = np.sum(plus_dm[1 : period + 1])
    smooth_minus[period] = np.sum(minus_dm[1 : period + 1])

    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - (smooth_tr[i - 1] / period) + tr[i]
        smooth_plus[i] = smooth_plus[i - 1] - (smooth_plus[i - 1] / period) + plus_dm[i]
        smooth_minus[i] = smooth_minus[i - 1] - (smooth_minus[i - 1] / period) + minus_dm[i]

    # +DI and -DI
    plus_di = np.zeros(n, dtype=np.float64)
    minus_di = np.zeros(n, dtype=np.float64)
    dx = np.zeros(n, dtype=np.float64)

    for i in range(period, n):
        if smooth_tr[i] > 0:
            plus_di[i] = 100.0 * smooth_plus[i] / smooth_tr[i]
            minus_di[i] = 100.0 * smooth_minus[i] / smooth_tr[i]
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    # ADX = smoothed DX
    start = period * 2
    if start < n:
        adx[start] = np.mean(dx[period + 1 : start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx


# ============================================================
# Bollinger Bands
# ============================================================


def compute_bollinger(
    candles: list[Candle],
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (upper, middle, lower) Bollinger Bands."""
    closes = _closes(candles)
    n = len(closes)

    upper = np.full(n, np.nan, dtype=np.float64)
    middle = np.full(n, np.nan, dtype=np.float64)
    lower = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mid = np.mean(window)
        std = np.std(window, ddof=0)
        middle[i] = mid
        upper[i] = mid + std_dev * std
        lower[i] = mid - std_dev * std

    return upper, middle, lower


def compute_bb_bandwidth(
    upper: np.ndarray,
    lower: np.ndarray,
    middle: np.ndarray,
) -> np.ndarray:
    """BB Bandwidth = (upper - lower) / middle."""
    with np.errstate(divide="ignore", invalid="ignore"):
        bw = np.where(middle > 0, (upper - lower) / middle, np.nan)
    return bw


# ============================================================
# Parabolic SAR
# ============================================================


def compute_parabolic_sar(
    candles: list[Candle],
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.20,
) -> np.ndarray:
    """Parabolic SAR. Returns array of SAR values."""
    highs = _highs(candles)
    lows = _lows(candles)
    n = len(candles)

    sar = np.full(n, np.nan, dtype=np.float64)
    if n < 2:
        return sar

    # Initialize: assume uptrend if second candle closes higher
    is_long = candles[1].close >= candles[0].close
    af = af_start
    ep = highs[0] if is_long else lows[0]
    sar[0] = lows[0] if is_long else highs[0]

    for i in range(1, n):
        prev_sar = sar[i - 1]

        if is_long:
            sar_val = prev_sar + af * (ep - prev_sar)
            # SAR can't be above the prior two lows
            sar_val = min(sar_val, lows[i - 1])
            if i >= 2:
                sar_val = min(sar_val, lows[i - 2])

            if lows[i] < sar_val:
                # Reversal to short
                is_long = False
                sar_val = ep
                ep = lows[i]
                af = af_start
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + af_step, af_max)
        else:
            sar_val = prev_sar + af * (ep - prev_sar)
            # SAR can't be below the prior two highs
            sar_val = max(sar_val, highs[i - 1])
            if i >= 2:
                sar_val = max(sar_val, highs[i - 2])

            if highs[i] > sar_val:
                # Reversal to long
                is_long = True
                sar_val = ep
                ep = highs[i]
                af = af_start
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + af_step, af_max)

        sar[i] = sar_val

    return sar


# ============================================================
# Heikin-Ashi
# ============================================================


def compute_heikin_ashi(candles: list[Candle]) -> list[Candle]:
    """Convert regular candles to Heikin-Ashi candles."""
    if not candles:
        return []

    ha_candles: list[Candle] = []
    prev_ha_open = candles[0].open
    prev_ha_close = (candles[0].open + candles[0].high + candles[0].low + candles[0].close) / 4.0

    for i, c in enumerate(candles):
        ha_close = (c.open + c.high + c.low + c.close) / 4.0
        ha_open = (prev_ha_open + prev_ha_close) / 2.0
        ha_high = max(c.high, ha_open, ha_close)
        ha_low = min(c.low, ha_open, ha_close)

        ha_candles.append(Candle(
            timestamp=c.timestamp,
            open=ha_open,
            high=ha_high,
            low=ha_low,
            close=ha_close,
            volume=c.volume,
            timeframe=c.timeframe,
            closed=c.closed,
        ))

        prev_ha_open = ha_open
        prev_ha_close = ha_close

    return ha_candles


# ============================================================
# MAD-based robust volatility (for G_VOL gate)
# ============================================================


def compute_rolling_mad(
    candles: list[Candle],
    window: int = 60,
) -> np.ndarray:
    """Rolling Median Absolute Deviation of returns.

    More robust than standard deviation against outliers.
    Used by G_VOL gate for volatility spike detection.
    """
    closes = _closes(candles)
    n = len(closes)
    mad = np.full(n, np.nan, dtype=np.float64)

    if n < 2:
        return mad

    # Log returns
    returns = np.diff(np.log(closes))
    returns = np.insert(returns, 0, 0.0)

    for i in range(window, n):
        window_returns = returns[i - window + 1 : i + 1]
        median = np.median(window_returns)
        mad[i] = np.median(np.abs(window_returns - median))

    return mad
