"""
DriftWrapper — thin abstraction over driftpy DriftClient.

Handles initialization, subscription, precision conversions,
and typed helpers for common trading operations.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair

from driftpy.drift_client import DriftClient, AccountSubscriptionConfig
from driftpy.drift_user import DriftUser
from driftpy.types import (
    MarketType,
    OrderParams,
    OrderType,
    OrderTriggerCondition,
    PositionDirection,
    PostOnlyParams,
)

from warpath import config
from warpath.config import Direction

logger = logging.getLogger(__name__)


def _load_keypair() -> Keypair:
    """Load Solana keypair from private key or JSON file."""
    if config.KEYPAIR_PATH:
        path = Path(config.KEYPAIR_PATH)
        data = json.loads(path.read_text())
        return Keypair.from_bytes(bytes(data))
    if config.PRIVATE_KEY:
        return Keypair.from_base58_string(config.PRIVATE_KEY)
    raise ValueError("No PRIVATE_KEY or KEYPAIR_PATH configured")


class DriftWrapper:
    """Production wrapper around driftpy DriftClient."""

    def __init__(self) -> None:
        self.client: DriftClient | None = None
        self._users: dict[int, DriftUser] = {}
        self._last_rpc_success: float = time.time()
        self._connected: bool = False

    async def initialize(self) -> None:
        """Connect to Drift and subscribe to market data."""
        kp = _load_keypair()
        connection = AsyncClient(config.RPC_URL_PRIMARY)

        self.client = DriftClient(
            connection=connection,
            wallet=kp,
            env=config.DRIFT_ENV,
            perp_market_indexes=[config.PERP_MARKET_INDEX],
            spot_market_indexes=[config.SPOT_MARKET_INDEX],
            account_subscription=AccountSubscriptionConfig("websocket"),
            active_sub_account_id=config.SUB_ACCOUNT_ID,
        )

        await self.client.subscribe()
        self._connected = True
        self._last_rpc_success = time.time()
        logger.info(
            "DriftWrapper initialized: env=%s market=%d sub_account=%d",
            config.DRIFT_ENV,
            config.PERP_MARKET_INDEX,
            config.SUB_ACCOUNT_ID,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        if self.client:
            await self.client.unsubscribe()
            self._connected = False
            logger.info("DriftWrapper shut down")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def rpc_age_s(self) -> float:
        """Seconds since last successful RPC interaction."""
        return time.time() - self._last_rpc_success

    # --------------------------------------------------------
    # Oracle / Market Data
    # --------------------------------------------------------

    def get_oracle_price(self) -> float:
        """Current oracle price for the primary perp market (human-readable)."""
        assert self.client is not None
        data = self.client.get_oracle_price_data_for_perp_market(config.PERP_MARKET_INDEX)
        self._last_rpc_success = time.time()
        return data.price / config.PRICE_PRECISION

    def get_funding_rate(self) -> float:
        """Current predicted funding rate for SOL-PERP."""
        assert self.client is not None
        market = self.client.get_perp_market_account(config.PERP_MARKET_INDEX)
        # last_funding_rate is per-period, scaled by PRICE_PRECISION
        return market.amm.last_funding_rate / config.PRICE_PRECISION

    # --------------------------------------------------------
    # Account / Margin
    # --------------------------------------------------------

    def get_user(self, sub_account_id: int | None = None) -> DriftUser:
        """Get or create a DriftUser for account queries."""
        sa = sub_account_id if sub_account_id is not None else config.SUB_ACCOUNT_ID
        if sa not in self._users:
            assert self.client is not None
            self._users[sa] = self.client.get_user(sa)
        return self._users[sa]

    def get_margin_ratio(self, sub_account_id: int | None = None) -> float:
        """Margin ratio: total_collateral / maintenance_margin_req.

        Uses hysteresis thresholds in G_LIQ (MG Patch 2).
        Returns float('inf') if no margin requirement.
        """
        user = self.get_user(sub_account_id)
        total_collateral = user.get_total_collateral()
        margin_req = user.get_margin_requirement("maintenance")
        self._last_rpc_success = time.time()
        if margin_req == 0:
            return float("inf")
        return total_collateral / margin_req

    def get_free_collateral(self, sub_account_id: int | None = None) -> float:
        """Free collateral in USDC (human-readable)."""
        user = self.get_user(sub_account_id)
        return user.get_free_collateral() / config.QUOTE_PRECISION

    def get_nav(self, sub_account_id: int | None = None) -> float:
        """NAV = total collateral (includes unrealized PnL). MG Patch 7."""
        user = self.get_user(sub_account_id)
        return user.get_total_collateral() / config.QUOTE_PRECISION

    def get_perp_position(self, sub_account_id: int | None = None):
        """Get open perp position for primary market. Returns None if flat."""
        user = self.get_user(sub_account_id)
        try:
            pos = user.get_perp_position(config.PERP_MARKET_INDEX)
            if pos and pos.base_asset_amount != 0:
                return pos
        except Exception:
            pass
        return None

    def get_unrealized_pnl(self, sub_account_id: int | None = None) -> float:
        """Unrealized PnL in USDC."""
        user = self.get_user(sub_account_id)
        return user.get_unrealized_pnl(with_funding=True) / config.QUOTE_PRECISION

    def get_open_orders(self, sub_account_id: int | None = None) -> list:
        """Get all open orders for this sub-account."""
        user = self.get_user(sub_account_id)
        return user.get_open_orders()

    # --------------------------------------------------------
    # Order Placement
    # --------------------------------------------------------

    async def place_oracle_limit_order(
        self,
        direction: Direction,
        size_usd: float,
        offset_bps: int,
        user_order_id: int = 0,
        reduce_only: bool = False,
    ) -> str:
        """Place a post-only oracle limit order.

        MG Patch 5: Directional offsets.
        LONG  = oracle * (1 - offset)  → buy below oracle
        SHORT = oracle * (1 + offset)  → sell above oracle
        """
        assert self.client is not None

        oracle_price = self.get_oracle_price()
        base_amount = int((size_usd / oracle_price) * config.BASE_PRECISION)

        # Oracle offset in price precision (signed)
        offset_frac = offset_bps / 10_000
        if direction == Direction.LONG:
            offset_raw = -int(offset_frac * oracle_price * config.PRICE_PRECISION)
        else:
            offset_raw = int(offset_frac * oracle_price * config.PRICE_PRECISION)

        pos_dir = (
            PositionDirection.Long()
            if direction == Direction.LONG
            else PositionDirection.Short()
        )

        order = OrderParams(
            order_type=OrderType.Limit(),
            market_type=MarketType.Perp(),
            market_index=config.PERP_MARKET_INDEX,
            direction=pos_dir,
            base_asset_amount=base_amount,
            price=0,
            oracle_price_offset=offset_raw,
            post_only=PostOnlyParams.MustPostOnly(),
            user_order_id=user_order_id,
            reduce_only=reduce_only,
        )

        if config.DRY_RUN:
            logger.info(
                "[DRY_RUN] place_oracle_limit: %s %.2f USD offset=%dbps order_id=%d",
                direction.value, size_usd, offset_bps, user_order_id,
            )
            return f"dry_run_{user_order_id}"

        sig = await self.client.place_perp_order(order)
        self._last_rpc_success = time.time()
        logger.info(
            "Placed oracle limit: %s %.2f USD offset=%dbps sig=%s",
            direction.value, size_usd, offset_bps, sig,
        )
        return str(sig)

    async def place_trigger_order(
        self,
        direction: Direction,
        size_base: int,
        trigger_price: float,
        is_stop_loss: bool,
        user_order_id: int = 0,
    ) -> str:
        """Place a trigger (TP/SL) order on Drift.

        SL for LONG: trigger Below, close direction Short
        TP for LONG: trigger Above, close direction Short
        SL for SHORT: trigger Above, close direction Long
        TP for SHORT: trigger Below, close direction Long
        """
        assert self.client is not None

        if direction == Direction.LONG:
            close_dir = PositionDirection.Short()
            trigger_cond = (
                OrderTriggerCondition.Below()
                if is_stop_loss
                else OrderTriggerCondition.Above()
            )
        else:
            close_dir = PositionDirection.Long()
            trigger_cond = (
                OrderTriggerCondition.Above()
                if is_stop_loss
                else OrderTriggerCondition.Below()
            )

        order = OrderParams(
            order_type=OrderType.TriggerMarket(),
            market_type=MarketType.Perp(),
            market_index=config.PERP_MARKET_INDEX,
            direction=close_dir,
            base_asset_amount=abs(size_base),
            trigger_price=int(trigger_price * config.PRICE_PRECISION),
            trigger_condition=trigger_cond,
            reduce_only=True,
            user_order_id=user_order_id,
        )

        if config.DRY_RUN:
            logger.info(
                "[DRY_RUN] place_trigger: %s %s trigger=%.4f size=%d",
                "SL" if is_stop_loss else "TP",
                direction.value, trigger_price, size_base,
            )
            return f"dry_run_trigger_{user_order_id}"

        sig = await self.client.place_perp_order(order)
        self._last_rpc_success = time.time()
        logger.info(
            "Placed trigger %s: %s trigger=%.4f sig=%s",
            "SL" if is_stop_loss else "TP",
            direction.value, trigger_price, sig,
        )
        return str(sig)

    async def place_market_close(
        self,
        direction: Direction,
        size_base: int,
        user_order_id: int = 0,
    ) -> str:
        """Emergency market close order (used by watcher fallback)."""
        assert self.client is not None

        close_dir = (
            PositionDirection.Short()
            if direction == Direction.LONG
            else PositionDirection.Long()
        )

        order = OrderParams(
            order_type=OrderType.Market(),
            market_type=MarketType.Perp(),
            market_index=config.PERP_MARKET_INDEX,
            direction=close_dir,
            base_asset_amount=abs(size_base),
            reduce_only=True,
            user_order_id=user_order_id,
        )

        if config.DRY_RUN:
            logger.info(
                "[DRY_RUN] market_close: %s size=%d", direction.value, size_base,
            )
            return f"dry_run_close_{user_order_id}"

        sig = await self.client.place_perp_order(order)
        self._last_rpc_success = time.time()
        logger.info("Market close: %s size=%d sig=%s", direction.value, size_base, sig)
        return str(sig)

    async def cancel_order(self, order_id: int | None = None) -> None:
        """Cancel a specific order or all perp orders on the market."""
        assert self.client is not None

        if config.DRY_RUN:
            logger.info("[DRY_RUN] cancel_order: %s", order_id)
            return

        if order_id is not None:
            await self.client.cancel_order(order_id)
        else:
            await self.client.cancel_orders(
                MarketType.Perp(), config.PERP_MARKET_INDEX
            )
        self._last_rpc_success = time.time()

    async def cancel_all_orders(self) -> None:
        """Cancel ALL orders across all markets. Used by kill switch."""
        assert self.client is not None
        if config.DRY_RUN:
            logger.info("[DRY_RUN] cancel_all_orders")
            return
        await self.client.cancel_orders()
        self._last_rpc_success = time.time()
