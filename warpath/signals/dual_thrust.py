"""
Dual Thrust Signal Scorer — breakout detection from DT range.

Score range: [-1.0, +1.0]
  Positive = long breakout (price > open + K1 * range)
  Negative = short breakout (price < open - K2 * range)

Range = K * max(HH - LC, HC - LL) over lookback period.
"""

from __future__ import annotations

from warpath import config
from warpath.data.candle_builder import Candle


def _compute_dt_range(candles: list[Candle], lookback: int) -> float:
    """Compute Dual Thrust range from prior candles.

    Range = max(HH - LC, HC - LL) where:
    HH = highest high, LC = lowest close, HC = highest close, LL = lowest low
    """
    if len(candles) < lookback:
        return 0.0

    window = candles[-lookback:]
    hh = max(c.high for c in window)
    ll = min(c.low for c in window)
    hc = max(c.close for c in window)
    lc = min(c.close for c in window)

    return max(hh - lc, hc - ll)


def score_dual_thrust(candles: list[Candle]) -> float:
    """Compute DT breakout signal score.

    Scoring components:
    1. Breakout from DT range (primary signal)
    2. Distance past trigger (conviction strength)
    3. Volume/momentum confirmation (tick count)
    """
    lookback = config.DT_LOOKBACK
    n = len(candles)

    if n < lookback + 2:
        return 0.0

    # Use candles before the current one for range calculation
    range_candles = candles[-(lookback + 1) : -1]
    dt_range = _compute_dt_range(range_candles, lookback)

    if dt_range <= 0:
        return 0.0

    # Current candle's open (or session open approximation)
    current = candles[-1]
    ref_open = candles[-2].close  # Use prior close as reference

    upper_trigger = ref_open + config.DT_K1 * dt_range
    lower_trigger = ref_open - config.DT_K2 * dt_range

    score = 0.0
    price = current.close

    # --- Component 1: Breakout detection ---
    if price > upper_trigger:
        score += 0.5
    elif price < lower_trigger:
        score -= 0.5
    else:
        # Inside range — weak directional bias based on position
        range_mid = (upper_trigger + lower_trigger) / 2
        if price > range_mid:
            score += 0.1
        else:
            score -= 0.1

    # --- Component 2: Breakout distance (conviction) ---
    if price > upper_trigger and dt_range > 0:
        distance_ratio = (price - upper_trigger) / dt_range
        score += min(0.3, distance_ratio * 0.3)
    elif price < lower_trigger and dt_range > 0:
        distance_ratio = (lower_trigger - price) / dt_range
        score -= min(0.3, distance_ratio * 0.3)

    # --- Component 3: Momentum (candle body direction) ---
    if current.is_green and price > upper_trigger:
        score += 0.2
    elif not current.is_green and price < lower_trigger:
        score -= 0.2

    return max(-1.0, min(1.0, score))
