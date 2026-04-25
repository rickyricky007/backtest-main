"""
VWAP Strategy
=============
Buy when price crosses above VWAP (bullish momentum).
Sell when price crosses below VWAP (bearish momentum).

VWAP = Σ(price × volume) / Σ(volume)
Resets every trading day at 09:15.

Best used for: intraday momentum trading on liquid stocks & indices.
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Any

from strategies.base_strategy import BaseStrategy, Signal


class VWAPStrategy(BaseStrategy):

    def __init__(
        self,
        symbol:         str,
        exchange:       str   = "NSE",
        quantity:       int   = 1,
        mode:           str   = "PAPER",
        min_volume:     int   = 1000,     # ignore ticks with volume below this
        band_pct:       float = 0.05,     # % band around VWAP to avoid whipsaws
    ):
        super().__init__(symbol=symbol, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.min_volume = min_volume
        self.band_pct   = band_pct / 100

        # VWAP state
        self._cum_pv:   float = 0.0   # cumulative price × volume
        self._cum_vol:  float = 0.0   # cumulative volume
        self._vwap:     float = 0.0
        self._prev_above: bool | None = None
        self._position: str = "FLAT"
        self._last_reset: str = ""

    @property
    def name(self) -> str:
        return "VWAP"

    @property
    def description(self) -> str:
        return "VWAP crossover — BUY above VWAP, SELL below VWAP (intraday, resets daily)"

    def _reset_if_new_day(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset:
            self._cum_pv      = 0.0
            self._cum_vol     = 0.0
            self._vwap        = 0.0
            self._prev_above  = None
            self._position    = "FLAT"
            self._last_reset  = today

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        self._reset_if_new_day()

        price  = tick.get("last_price", 0)
        volume = tick.get("volume_traded") or tick.get("volume", 0)

        if not price or volume < self.min_volume:
            return None

        # Update VWAP
        self._cum_pv  += price * volume
        self._cum_vol += volume
        self._vwap     = self._cum_pv / self._cum_vol if self._cum_vol else price
        vwap           = self._vwap
        band           = vwap * self.band_pct

        above = price > (vwap + band)
        below = price < (vwap - band)

        signal = None

        # Cross above VWAP → BUY
        if above and self._prev_above is False and self._position == "FLAT":
            signal = self._make_signal(
                action = "BUY",
                price  = price,
                reason = f"Price ₹{price:.2f} crossed above VWAP ₹{vwap:.2f}",
                meta   = {"vwap": round(vwap, 2)},
            )
            self._position = "LONG"

        # Cross below VWAP → SELL
        elif below and self._prev_above is True and self._position == "FLAT":
            signal = self._make_signal(
                action = "SELL",
                price  = price,
                reason = f"Price ₹{price:.2f} crossed below VWAP ₹{vwap:.2f}",
                meta   = {"vwap": round(vwap, 2)},
            )
            self._position = "SHORT"

        # Exit LONG if price falls back below VWAP
        elif self._position == "LONG" and below:
            signal = self._make_signal(
                action = "EXIT",
                price  = price,
                reason = f"Exit long — price fell below VWAP ₹{vwap:.2f}",
                meta   = {"vwap": round(vwap, 2)},
            )
            self._position = "FLAT"

        # Exit SHORT if price rises back above VWAP
        elif self._position == "SHORT" and above:
            signal = self._make_signal(
                action = "EXIT",
                price  = price,
                reason = f"Exit short — price rose above VWAP ₹{vwap:.2f}",
                meta   = {"vwap": round(vwap, 2)},
            )
            self._position = "FLAT"

        if above:
            self._prev_above = True
        elif below:
            self._prev_above = False

        return signal
