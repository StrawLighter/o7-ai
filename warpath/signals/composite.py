"""
Composite Signal Scorer — weighted combination of all 4 signals.

Applies regime-adjusted weights from config.REGIME_WEIGHTS.
Maps |composite_score| to entry tier and direction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from warpath import config
from warpath.config import Direction, Regime
from warpath.data.candle_builder import Candle
from warpath.data.indicators import (
    compute_atr,
    compute_adx,
    compute_bollinger,
    compute_bb_bandwidth,
    compute_heikin_ashi,
    compute_parabolic_sar,
)
from warpath.signals.bollinger import score_bollinger
from warpath.signals.dual_thrust import score_dual_thrust
from warpath.signals.heikin_ashi import score_heikin_ashi
from warpath.signals.parabolic_sar import score_parabolic_sar
from warpath.signals.regime import RegimeClassifier

logger = logging.getLogger(__name__)


@dataclass
class CompositeSignal:
    composite_score: float
    direction: Direction
    tier: int
    regime: Regime
    bb_score: float = 0.0
    sar_score: float = 0.0
    ha_score: float = 0.0
    dt_score: float = 0.0
    atr: float = 0.0
    adx: float = 0.0
    bb_bandwidth: float = 0.0
    oracle_price: float = 0.0


class CompositeScorer:
    """Combines 4 signal scores with regime-adjusted weights."""

    def __init__(self) -> None:
        self._regime_classifier = RegimeClassifier()

    @property
    def regime(self) -> Regime:
        return self._regime_classifier.regime

    def score(self, candles: list[Candle], oracle_price: float = 0.0) -> CompositeSignal:
        """Compute the full composite signal from candle data.

        Steps:
        1. Compute all indicators from candles
        2. Classify regime (ADX + BB bandwidth)
        3. Score each signal independently
        4. Apply regime-adjusted weights
        5. Map to direction and tier
        """
        n = len(candles)
        if n < config.MIN_CANDLES_WARMUP:
            return CompositeSignal(
                composite_score=0.0,
                direction=Direction.NEUTRAL,
                tier=0,
                regime=self._regime_classifier.regime,
            )

        # Compute indicators
        atr = compute_atr(candles, config.ATR_PERIOD)
        adx = compute_adx(candles, config.ADX_PERIOD)
        upper, middle, lower = compute_bollinger(candles, config.BB_PERIOD, config.BB_STD_DEV)
        bb_bw = compute_bb_bandwidth(upper, lower, middle)
        sar = compute_parabolic_sar(candles, config.SAR_AF_START, config.SAR_AF_STEP, config.SAR_AF_MAX)
        ha_candles = compute_heikin_ashi(candles)

        # Classify regime
        regime = self._regime_classifier.classify(adx, bb_bw)

        # Score each signal
        bb_s = score_bollinger(candles, upper, middle, lower, bb_bw)
        sar_s = score_parabolic_sar(candles, sar, atr)
        ha_s = score_heikin_ashi(ha_candles)
        dt_s = score_dual_thrust(candles)

        # Get regime weights
        weights = config.REGIME_WEIGHTS.get(
            regime, config.REGIME_WEIGHTS[Regime.TRANSITIONAL]
        )

        # Weighted composite
        composite = (
            weights["bb"] * bb_s
            + weights["sar"] * sar_s
            + weights["ha"] * ha_s
            + weights["dt"] * dt_s
        )

        # Determine direction
        if composite > 0:
            direction = Direction.LONG
        elif composite < 0:
            direction = Direction.SHORT
        else:
            direction = Direction.NEUTRAL

        # Determine tier from |composite|
        abs_composite = abs(composite)
        if abs_composite >= config.TIER_3_THRESHOLD:
            tier = 3
        elif abs_composite >= config.TIER_2_THRESHOLD:
            tier = 2
        elif abs_composite >= config.TIER_1_THRESHOLD:
            tier = 1
        else:
            tier = 0  # No entry

        # Get latest ATR and ADX values
        latest_atr = float(atr[-1]) if not np.isnan(atr[-1]) else 0.0
        latest_adx = float(adx[-1]) if not np.isnan(adx[-1]) else 0.0
        latest_bw = float(bb_bw[-1]) if not np.isnan(bb_bw[-1]) else 0.0

        return CompositeSignal(
            composite_score=composite,
            direction=direction,
            tier=tier,
            regime=regime,
            bb_score=bb_s,
            sar_score=sar_s,
            ha_score=ha_s,
            dt_score=dt_s,
            atr=latest_atr,
            adx=latest_adx,
            bb_bandwidth=latest_bw,
            oracle_price=oracle_price,
        )
