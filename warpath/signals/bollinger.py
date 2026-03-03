"""
Bollinger Bands Signal Scorer — squeeze/breakout pattern detection.

Score range: [-1.0, +1.0]
  Positive = long bias (breakout above upper band, squeeze resolution up)
  Negative = short bias (breakout below lower band, squeeze resolution down)
"""

from __future__ import annotations

import numpy as np

from warpath.data.candle_builder import Candle


def score_bollinger(
    candles: list[Candle],
    upper: np.ndarray,
    middle: np.ndarray,
    lower: np.ndarray,
    bb_bandwidth: np.ndarray,
) -> float:
    """Compute BB signal score from candle data and pre-computed bands.

    Patterns detected:
    1. Band walk (price hugging upper/lower band) = strong trend
    2. Squeeze breakout (low BW → expansion + directional close) = entry signal
    3. Mean reversion from bands (touch band → reverse) = counter-trend
    """
    n = len(candles)
    if n < 5 or np.isnan(upper[-1]) or np.isnan(lower[-1]):
        return 0.0

    close = candles[-1].close
    prev_close = candles[-2].close
    ub = upper[-1]
    mb = middle[-1]
    lb = lower[-1]
    bw_current = bb_bandwidth[-1] if not np.isnan(bb_bandwidth[-1]) else 0.0

    # BW percentile over recent history (for squeeze detection)
    valid_bw = bb_bandwidth[~np.isnan(bb_bandwidth)]
    if len(valid_bw) < 10:
        bw_percentile = 0.5
    else:
        bw_percentile = float(np.sum(valid_bw < bw_current) / len(valid_bw))

    score = 0.0
    band_range = ub - lb if ub > lb else 1e-8

    # --- Pattern 1: Squeeze breakout ---
    # BW in bottom 20% = squeeze, look for breakout direction
    is_squeeze = bw_percentile < 0.20
    if is_squeeze:
        if close > ub:
            score += 0.5  # Bullish breakout from squeeze
        elif close < lb:
            score -= 0.5  # Bearish breakout from squeeze
        elif close > mb and prev_close <= mb:
            score += 0.2  # Crossing above middle during squeeze
        elif close < mb and prev_close >= mb:
            score -= 0.2

    # --- Pattern 2: Band walk ---
    # Price consistently near upper or lower band
    walk_count_up = 0
    walk_count_down = 0
    lookback = min(5, n)

    for i in range(-lookback, 0):
        idx = n + i
        if idx < 0 or np.isnan(upper[idx]):
            continue
        c = candles[idx].close
        band_pos = (c - lower[idx]) / max(upper[idx] - lower[idx], 1e-8)
        if band_pos > 0.8:
            walk_count_up += 1
        elif band_pos < 0.2:
            walk_count_down += 1

    if walk_count_up >= 3:
        score += 0.3
    elif walk_count_down >= 3:
        score -= 0.3

    # --- Pattern 3: Position relative to bands ---
    # Normalized position: 0 = at lower band, 1 = at upper band
    band_position = (close - lb) / band_range

    if band_position > 1.0:
        score += 0.2  # Above upper band
    elif band_position < 0.0:
        score -= 0.2  # Below lower band
    elif band_position > 0.5:
        score += 0.1 * (band_position - 0.5) * 2
    else:
        score -= 0.1 * (0.5 - band_position) * 2

    return max(-1.0, min(1.0, score))
