"""
Heikin-Ashi Signal Scorer — momentum via HA candle patterns.

Score range: [-1.0, +1.0]
  Positive = long momentum (green HA streak, strong bodies)
  Negative = short momentum (red HA streak, strong bodies)
"""

from __future__ import annotations

from warpath.data.candle_builder import Candle


def score_heikin_ashi(ha_candles: list[Candle]) -> float:
    """Compute HA momentum score.

    Scoring components:
    1. Color streak length (consecutive green/red HA candles)
    2. Body-to-range ratio (conviction — bigger bodies = stronger)
    3. Wick analysis (no lower wick on green = very bullish)
    """
    n = len(ha_candles)
    if n < 3:
        return 0.0

    score = 0.0

    # --- Component 1: Color streak ---
    streak = 0
    is_green = ha_candles[-1].is_green

    for i in range(n - 1, -1, -1):
        if ha_candles[i].is_green == is_green:
            streak += 1
        else:
            break

    # Cap streak contribution at 5 candles
    streak_capped = min(streak, 5)
    streak_score = streak_capped * 0.1  # max 0.5

    if is_green:
        score += streak_score
    else:
        score -= streak_score

    # --- Component 2: Body dominance ---
    # Average body-to-range ratio over last 3 candles
    body_ratios = []
    for i in range(-min(3, n), 0):
        c = ha_candles[n + i]
        if c.range > 0:
            body_ratios.append(c.body / c.range)

    if body_ratios:
        avg_body_ratio = sum(body_ratios) / len(body_ratios)
        # Strong bodies (>0.6) add conviction
        body_score = min(0.3, avg_body_ratio * 0.4)
        if is_green:
            score += body_score
        else:
            score -= body_score

    # --- Component 3: Wick analysis ---
    latest = ha_candles[-1]
    if latest.range > 0:
        if latest.is_green:
            # No lower wick on green = very bullish
            lower_wick = latest.open - latest.low  # HA open is always between prev values
            lower_wick_ratio = lower_wick / latest.range
            if lower_wick_ratio < 0.05:
                score += 0.2  # Almost no lower wick = strong buying
        else:
            # No upper wick on red = very bearish
            upper_wick = latest.high - latest.open
            upper_wick_ratio = upper_wick / latest.range
            if upper_wick_ratio < 0.05:
                score -= 0.2

    return max(-1.0, min(1.0, score))
