"""
RSI Strategy
============
Emits BUY when RSI crosses below oversold threshold.
Emits SELL when RSI crosses above overbought threshold.
Emits EXIT when RSI returns to neutral zone.

Configurable:
    period      — RSI period (default 14)
    oversold    — RSI level to trigger BUY (default 30)
    overbought  — RSI level to trigger SELL (default 70)
    warmup      — minimum candles before trading (default period+2)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from strategies.base_strategy import BaseStrategy, Signal


class RSIStrategy(BaseStrategy):

    def __init__(
        self,
        symbol:     str,
        exchange:   str  = "NSE",
        quantity:   int  = 1,
        mode:       str  = "PAPER",
        period:     int  = 14,
        oversold:   float = 30.0,
        overbought: float = 70.0,
    ):
        super().__init__(symbol=symbol, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.period     = period
        self.oversold   = oversold
        self.overbought = overbought
        self._warmup    = period + 2

        # Track previous RSI to detect crossovers
        self._prev_rsi: float | None = None
        self._position: str = "FLAT"  # "FLAT", "LONG", "SHORT"

    @property
    def name(self) -> str:
        return f"RSI_{self.period}"

    @property
    def description(self) -> str:
        return (
            f"RSI({self.period}) strategy — "
            f"BUY below {self.oversold}, SELL above {self.overbought}"
        )

    def _calculate_rsi(self, closes: list[float]) -> float:
        """Wilder's smoothed RSI."""
        if len(closes) < self.period + 1:
            return 50.0
        arr    = np.array(closes[-(self.period * 3):])  # use last 3x period for accuracy
        deltas = np.diff(arr)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[:self.period]))
        avg_loss = float(np.mean(losses[:self.period]))

        for i in range(self.period, len(gains)):
            avg_gain = (avg_gain * (self.period - 1) + gains[i]) / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        price = tick.get("last_price")
        if not price:
            return None

        self._add_price(float(price))

        # Need enough data to compute RSI
        if len(self._price_buffer) < self._warmup:
            return None

        curr_rsi = self._calculate_rsi(self._price_buffer)

        signal = None

        # ── BUY: RSI crosses below oversold ──────────────────────────────────
        if (
            self._prev_rsi is not None
            and self._prev_rsi >= self.oversold
            and curr_rsi < self.oversold
            and self._position == "FLAT"
        ):
            signal = self._make_signal(
                action  = "BUY",
                price   = price,
                reason  = f"RSI crossed below {self.oversold} (RSI={curr_rsi})",
                meta    = {"rsi": curr_rsi, "prev_rsi": self._prev_rsi},
            )
            self._position = "LONG"

        # ── SELL: RSI crosses above overbought ───────────────────────────────
        elif (
            self._prev_rsi is not None
            and self._prev_rsi <= self.overbought
            and curr_rsi > self.overbought
            and self._position == "FLAT"
        ):
            signal = self._make_signal(
                action  = "SELL",
                price   = price,
                reason  = f"RSI crossed above {self.overbought} (RSI={curr_rsi})",
                meta    = {"rsi": curr_rsi, "prev_rsi": self._prev_rsi},
            )
            self._position = "SHORT"

        # ── EXIT LONG: RSI recovers above 50 ────────────────────────────────
        elif self._position == "LONG" and curr_rsi > 50:
            signal = self._make_signal(
                action  = "EXIT",
                price   = price,
                reason  = f"RSI recovered above 50 — exiting long (RSI={curr_rsi})",
                meta    = {"rsi": curr_rsi},
            )
            self._position = "FLAT"

        # ── EXIT SHORT: RSI falls back below 50 ─────────────────────────────
        elif self._position == "SHORT" and curr_rsi < 50:
            signal = self._make_signal(
                action  = "EXIT",
                price   = price,
                reason  = f"RSI fell below 50 — exiting short (RSI={curr_rsi})",
                meta    = {"rsi": curr_rsi},
            )
            self._position = "FLAT"

        self._prev_rsi = curr_rsi
        return signal
