"""
Real-time OHLCV candle builder from oracle price ticks.

Maintains rolling deque-based windows for 1m, 5m, 15m timeframes.
Emits completed candles for downstream indicator computation.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

from warpath import config

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    timestamp: float      # candle open time (epoch)
    open: float
    high: float
    low: float
    close: float
    volume: int = 0       # tick count for this candle
    timeframe: str = "5m"
    closed: bool = False

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_green(self) -> bool:
        return self.close >= self.open


class CandleBuilder:
    """Builds multi-timeframe OHLCV candles from raw oracle ticks."""

    def __init__(
        self,
        timeframes: list[str] | None = None,
        max_candles: int = 200,
    ) -> None:
        self.timeframes = timeframes or ["1m", "5m", "15m"]
        self.max_candles = max_candles

        # Completed candle history per timeframe
        self.candles: dict[str, deque[Candle]] = {
            tf: deque(maxlen=max_candles) for tf in self.timeframes
        }

        # Current (in-progress) candle per timeframe
        self._current: dict[str, Candle | None] = {
            tf: None for tf in self.timeframes
        }

        self._tick_count: int = 0

    def on_tick(self, price: float, timestamp: float | None = None) -> list[Candle]:
        """Process a new price tick. Returns list of newly closed candles."""
        ts = timestamp or time.time()
        self._tick_count += 1
        closed: list[Candle] = []

        for tf in self.timeframes:
            interval = config.TIMEFRAME_SECONDS[tf]
            candle_start = (ts // interval) * interval

            current = self._current[tf]

            if current is None or candle_start > current.timestamp:
                # Close the previous candle if it exists
                if current is not None:
                    current.closed = True
                    self.candles[tf].append(current)
                    closed.append(current)

                # Start a new candle
                self._current[tf] = Candle(
                    timestamp=candle_start,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=1,
                    timeframe=tf,
                )
            else:
                # Update current candle
                current.high = max(current.high, price)
                current.low = min(current.low, price)
                current.close = price
                current.volume += 1

        return closed

    def get_candles(self, timeframe: str, count: int | None = None) -> list[Candle]:
        """Get completed candles for a timeframe, oldest first."""
        candles = list(self.candles.get(timeframe, []))
        if count is not None:
            candles = candles[-count:]
        return candles

    def get_current(self, timeframe: str) -> Candle | None:
        """Get the in-progress candle for a timeframe."""
        return self._current.get(timeframe)

    @property
    def is_warm(self) -> bool:
        """True if we have enough candles for all indicators."""
        tf = config.CANDLE_TIMEFRAME
        return len(self.candles.get(tf, [])) >= config.MIN_CANDLES_WARMUP

    @property
    def total_ticks(self) -> int:
        return self._tick_count
