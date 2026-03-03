"""
Position sizing — tiered sizing with regime-coupled leverage.

Maps composite signal strength to tier, applies regime multiplier,
and ensures size never exceeds free collateral.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from warpath import config
from warpath.config import Direction, GateResult, LeverageTier, Regime

logger = logging.getLogger(__name__)


@dataclass
class SizingResult:
    tier: int
    size_usd: float
    leverage: float
    offset_bps: int
    timeout_s: int
    atr_mult: float
    direction: Direction


def select_tier(signal_strength: float) -> LeverageTier | None:
    """Select leverage tier based on absolute composite signal strength.

    Higher signal strength → higher tier → more leverage, tighter entry.
    Returns None if signal is too weak for any tier.
    """
    abs_s = abs(signal_strength)

    # Check tiers from highest to lowest
    for tier_num in (3, 2, 1):
        tier = config.LEVERAGE_TIERS[tier_num]
        if abs_s >= tier.signal_min:
            return tier

    return None


def compute_effective_leverage(
    base_leverage: float,
    regime: Regime,
    vol_cap: float = 1.0,
    spread_cap: float = 1.0,
    funding_cap: float = 1.0,
) -> float:
    """Effective leverage = base × regime_mult × vol_cap × spread_cap × funding_cap.

    Each cap is in [0, 1] and reduces leverage from the base.
    """
    regime_mult = config.REGIME_LEVERAGE_MULT.get(regime, 0.85)
    effective = base_leverage * regime_mult * vol_cap * spread_cap * funding_cap
    # Clamp to 10–25x range
    return max(10.0, min(25.0, effective))


def compute_size(
    free_collateral: float,
    signal_strength: float,
    direction: Direction,
    regime: Regime,
    gate_result: GateResult | None = None,
    oracle_price: float = 0.0,
    current_spread_bps: float = 0.0,
    current_funding_rate: float = 0.0,
) -> SizingResult | None:
    """Compute position size for a trade.

    Returns None if signal is too weak or collateral insufficient.
    """
    tier_def = select_tier(signal_strength)
    if tier_def is None:
        return None

    # Compute leverage caps
    vol_cap = 1.0
    spread_cap = 1.0
    funding_cap = 1.0

    if current_spread_bps > 0:
        spread_cap = min(1.0, config.MAX_SPREAD_BPS / current_spread_bps)

    # Adverse funding reduces leverage
    is_adverse = (
        (direction == Direction.LONG and current_funding_rate > 0)
        or (direction == Direction.SHORT and current_funding_rate < 0)
    )
    if is_adverse and abs(current_funding_rate) > 0:
        funding_cap = max(0.5, 1.0 - abs(current_funding_rate) * 100)

    effective_leverage = compute_effective_leverage(
        tier_def.base_leverage, regime, vol_cap, spread_cap, funding_cap,
    )

    # Apply G_VOL sizing modifier
    sizing_modifier = gate_result.sizing_modifier if gate_result else 1.0
    effective_leverage *= sizing_modifier

    # Position size in USD (notional)
    # Use a fraction of free collateral based on tier
    tier_alloc = {1: 0.30, 2: 0.50, 3: 0.70}
    collateral_fraction = tier_alloc.get(tier_def.tier, 0.30)
    margin_used = free_collateral * collateral_fraction * sizing_modifier
    size_usd = margin_used * effective_leverage

    # Safety: cap at free collateral * max allowed leverage
    max_size = free_collateral * 25.0
    size_usd = min(size_usd, max_size)

    # Minimum order size check
    if size_usd < 0.10:
        logger.warning("Size too small: $%.4f", size_usd)
        return None

    return SizingResult(
        tier=tier_def.tier,
        size_usd=size_usd,
        leverage=effective_leverage,
        offset_bps=tier_def.entry_offset_bps,
        timeout_s=tier_def.entry_timeout_s,
        atr_mult=tier_def.atr_mult,
        direction=direction,
    )
