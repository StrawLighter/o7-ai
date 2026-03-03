"""
Regime Classifier — ADX + BB bandwidth market regime detection.

Regimes: TREND, RANGE, VOLATILE, TRANSITIONAL
Minimum 5-candle duration before switching regime.
"""

from __future__ import annotations

import numpy as np

from warpath import config
from warpath.config import Regime


class RegimeClassifier:
    """Classifies current market regime from ADX and BB bandwidth."""

    def __init__(self) -> None:
        self._current: Regime = Regime.TRANSITIONAL
        self._regime_candle_count: int = 0

    @property
    def regime(self) -> Regime:
        return self._current

    def classify(self, adx: np.ndarray, bb_bandwidth: np.ndarray) -> Regime:
        """Classify regime from the latest ADX and BB bandwidth values.

        TREND:    ADX > 25 AND BB_bandwidth < 0.05
        RANGE:    ADX < 20 AND BB_bandwidth < 0.04
        VOLATILE: BB_bandwidth > 0.06 (regardless of ADX)
        TRANSITIONAL: everything else
        """
        # Get latest valid values
        latest_adx = self._latest_valid(adx)
        latest_bw = self._latest_valid(bb_bandwidth)

        if latest_adx is None or latest_bw is None:
            return self._current

        # Classify
        if latest_bw > config.REGIME_BW_VOLATILE:
            candidate = Regime.VOLATILE
        elif latest_adx > config.REGIME_ADX_TREND and latest_bw < config.REGIME_BW_TREND:
            candidate = Regime.TREND
        elif latest_adx < config.REGIME_ADX_RANGE and latest_bw < config.REGIME_BW_RANGE:
            candidate = Regime.RANGE
        else:
            candidate = Regime.TRANSITIONAL

        # Enforce minimum regime duration
        if candidate == self._current:
            self._regime_candle_count += 1
        else:
            self._regime_candle_count += 1
            if self._regime_candle_count >= config.REGIME_MIN_DURATION:
                self._current = candidate
                self._regime_candle_count = 0

        return self._current

    def _latest_valid(self, arr: np.ndarray) -> float | None:
        """Get the latest non-NaN value from an array."""
        for i in range(len(arr) - 1, -1, -1):
            if not np.isnan(arr[i]):
                return float(arr[i])
        return None
