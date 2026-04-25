"""
SMA Crossover Strategy
======================
Golden Cross  → BUY  (fast SMA crosses above slow SMA)
Death Cross   → SELL (fast SMA crosses below slow SMA)

Configurable:
    fast   — fast SMA period (default 20)
    slow   — slow SMA period (default 50)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from strategies.base_strategy import BaseStrategy, Signal


class SMAStrategy(BaseStrategy):

    def __init__(
        self,
        symbol:   str,
        exchange: str = "NSE",
        quantity: int = 1,
        mode:     str = "PAPER",
        fast:     int = 20,
        slow:     int = 50,
    ):
        super().__init__(symbol=symbol, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.fast = fast
        self.slow = slow

        self._prev_fast: float | None = None
        self._prev_slow: float | None = None
        self._position: str = "FLAT"

    @property
    def name(self) -> str:
        return f"SMA_{self.fast}_{self.slow}"

    @property
    def description(self) -> str:
        return (
            f"SMA Crossover — Golden Cross SMA({self.fast}) > SMA({self.slow}) → BUY, "
            f"Death Cross → SELL"
        )

    def _sma(self, period: int) -> float | None:
        if len(self._price_buffer) < period:
            return None
        return float(np.mean(self._price_buffer[-period:]))

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        price = tick.get("last_price")
        if not price:
            return None

        self._add_price(float(price))

        # Need enough data for slow SMA
        if len(self._price_buffer) < self.slow:
            return None

        curr_fast = self._sma(self.fast)
        curr_slow = self._sma(self.slow)

        if curr_fast is None or curr_slow is None:
            return None

        signal = None

        if self._prev_fast is not None and self._prev_slow is not None:

            # ── Golden Cross: fast crosses above slow → BUY ───────────────────
            if (
                self._prev_fast <= self._prev_slow
                and curr_fast > curr_slow
                and self._position != "LONG"
            ):
                signal = self._make_signal(
                    action  = "BUY",
                    price   = price,
                    reason  = f"Golden Cross — SMA{self.fast} crossed above SMA{self.slow}",
                    meta    = {"sma_fast": round(curr_fast, 2), "sma_slow": round(curr_slow, 2)},
                )
                self._position = "LONG"

            # ── Death Cross: fast crosses below slow → SELL ───────────────────
            elif (
                self._prev_fast >= self._prev_slow
                and curr_fast < curr_slow
                and self._position != "SHORT"
            ):
                signal = self._make_signal(
                    action  = "SELL",
                    price   = price,
                    reason  = f"Death Cross — SMA{self.fast} crossed below SMA{self.slow}",
                    meta    = {"sma_fast": round(curr_fast, 2), "sma_slow": round(curr_slow, 2)},
                )
                self._position = "SHORT"

        self._prev_fast = curr_fast
        self._prev_slow = curr_slow
        return signal
