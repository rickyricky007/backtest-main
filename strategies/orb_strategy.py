"""
Opening Range Breakout (ORB) Strategy
======================================
One of the most reliable intraday strategies.

Logic:
    1. First N minutes after market open (09:15–09:30) → build the "opening range"
       - Track high and low of this period
    2. After range is set:
       - Price breaks above range high → BUY (bullish breakout)
       - Price breaks below range low  → SELL (bearish breakout)
    3. Exit at end of day or when SL/target hit (handled by StopLossManager)

Configurable:
    range_minutes : how many minutes to build the opening range (default 15)
    buffer_pct    : % buffer above/below range to avoid false breakouts
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Any

from strategies.base_strategy import BaseStrategy, Signal


class ORBStrategy(BaseStrategy):

    def __init__(
        self,
        symbol:        str,
        exchange:      str   = "NSE",
        quantity:      int   = 1,
        mode:          str   = "PAPER",
        range_minutes: int   = 15,        # build range in first 15 min
        buffer_pct:    float = 0.1,       # 0.1% buffer to confirm breakout
    ):
        super().__init__(symbol=symbol, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.range_minutes = range_minutes
        self.buffer_pct    = buffer_pct / 100

        # ORB state
        self._range_high:    float | None = None
        self._range_low:     float | None = None
        self._range_locked:  bool         = False
        self._traded_today:  bool         = False
        self._position:      str          = "FLAT"
        self._last_reset:    str          = ""

        # Market open time
        self._open_time = dtime(9, 15)
        self._range_end = None  # set dynamically

    @property
    def name(self) -> str:
        return f"ORB_{self.range_minutes}m"

    @property
    def description(self) -> str:
        return (
            f"Opening Range Breakout ({self.range_minutes}min range) — "
            f"BUY on upside breakout, SELL on downside breakout"
        )

    def _reset_if_new_day(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset:
            self._range_high   = None
            self._range_low    = None
            self._range_locked = False
            self._traded_today = False
            self._position     = "FLAT"
            self._last_reset   = today
            # Set range end time
            from datetime import time, timedelta
            open_dt        = datetime.strptime(f"{today} 09:15", "%Y-%m-%d %H:%M")
            range_end_dt   = open_dt + timedelta(minutes=self.range_minutes)
            self._range_end = range_end_dt.time()

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        self._reset_if_new_day()

        price = tick.get("last_price", 0)
        if not price:
            return None

        now = datetime.now().time()

        # Before market open — ignore
        if now < self._open_time:
            return None

        # Building opening range
        if not self._range_locked:
            if now <= self._range_end:
                # Update range high/low
                self._range_high = max(self._range_high or price, price)
                self._range_low  = min(self._range_low  or price, price)
                return None
            else:
                # Range period over — lock it
                self._range_locked = True
                print(
                    f"[ORB] {self.symbol} range locked: "
                    f"H=₹{self._range_high:.2f} L=₹{self._range_low:.2f}"
                )

        # Only trade once per day
        if self._traded_today:
            # Check exit (end of day)
            if now >= dtime(15, 15) and self._position != "FLAT":
                signal = self._make_signal(
                    action = "EXIT",
                    price  = price,
                    reason = "End of day exit",
                    meta   = {"range_high": self._range_high, "range_low": self._range_low},
                )
                self._position = "FLAT"
                return signal
            return None

        # Buffer levels
        breakout_high = round(self._range_high * (1 + self.buffer_pct), 2)
        breakout_low  = round(self._range_low  * (1 - self.buffer_pct), 2)

        signal = None

        # Bullish breakout
        if price >= breakout_high and self._position == "FLAT":
            signal = self._make_signal(
                action = "BUY",
                price  = price,
                reason = f"ORB upside breakout — price ₹{price:.2f} > range high ₹{breakout_high:.2f}",
                meta   = {
                    "range_high":    self._range_high,
                    "range_low":     self._range_low,
                    "breakout_level": breakout_high,
                },
            )
            self._position    = "LONG"
            self._traded_today = True

        # Bearish breakout
        elif price <= breakout_low and self._position == "FLAT":
            signal = self._make_signal(
                action = "SELL",
                price  = price,
                reason = f"ORB downside breakout — price ₹{price:.2f} < range low ₹{breakout_low:.2f}",
                meta   = {
                    "range_high":    self._range_high,
                    "range_low":     self._range_low,
                    "breakout_level": breakout_low,
                },
            )
            self._position    = "SHORT"
            self._traded_today = True

        return signal
