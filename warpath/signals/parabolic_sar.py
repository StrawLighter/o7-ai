"""
Parabolic SAR Signal Scorer — SAR flip detection and distance scoring.

Score range: [-1.0, +1.0]
  Positive = long bias (SAR below price, recent flip to long)
  Negative = short bias (SAR above price, recent flip to short)
"""

from __future__ import annotations

import numpy as np

from warpath.data.candle_builder import Candle


def score_parabolic_sar(
    candles: list[Candle],
    sar: np.ndarray,
    atr: np.ndarray,
) -> float:
    """Compute SAR signal score.

    Scoring components:
    1. SAR position relative to price (above/below)
    2. Recent SAR flip (reversal signal — strongest component)
    3. SAR-price distance normalized by ATR (conviction strength)
    """
    n = len(candles)
    if n < 3 or np.isnan(sar[-1]) or np.isnan(sar[-2]):
        return 0.0

    close = candles[-1].close
    sar_current = sar[-1]
    sar_prev = sar[-2]
    current_atr = atr[-1] if not np.isnan(atr[-1]) else abs(close * 0.02)

    score = 0.0

    # --- Component 1: SAR position ---
    # SAR below price = bullish, SAR above = bearish
    is_long = close > sar_current
    if is_long:
        score += 0.3
    else:
        score -= 0.3

    # --- Component 2: SAR flip detection ---
    # A flip is when SAR crosses price between consecutive candles
    prev_close = candles[-2].close
    was_long = prev_close > sar_prev

    if is_long and not was_long:
        # Bearish → Bullish flip (strong long signal)
        score += 0.5
    elif not is_long and was_long:
        # Bullish → Bearish flip (strong short signal)
        score -= 0.5

    # Look back further for recent flips (weaker signal)
    for i in range(3, min(6, n)):
        idx = n - i
        if idx < 1 or np.isnan(sar[idx]) or np.isnan(sar[idx - 1]):
            continue
        c = candles[idx].close
        pc = candles[idx - 1].close
        s = sar[idx]
        ps = sar[idx - 1]
        if (c > s) and (pc <= ps):
            score += 0.1  # Recent bullish flip
            break
        elif (c < s) and (pc >= ps):
            score -= 0.1
            break

    # --- Component 3: Distance from SAR (conviction) ---
    # Larger distance = stronger trend confirmation
    if current_atr > 0:
        distance_atr = abs(close - sar_current) / current_atr
        distance_score = min(0.2, distance_atr * 0.1)
        if is_long:
            score += distance_score
        else:
            score -= distance_score

    return max(-1.0, min(1.0, score))
