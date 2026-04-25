"""
Options Strategies
==================
Implements common F&O strategies:

    ShortStraddleStrategy — sell ATM CE + ATM PE (profit from low volatility)
    ShortStrangleStrategy — sell OTM CE + OTM PE (wider range, lower premium)
    LongStraddleStrategy  — buy ATM CE + ATM PE (profit from big move)

All strategies:
    - Auto-find ATM/OTM strikes via Kite instruments
    - Emit signals with instrument tokens for fast execution
    - Handle expiry management (exit before expiry day)
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal


def _get_atm_strike(spot: float, step: float = 50.0) -> float:
    """Round spot to nearest strike step."""
    return round(round(spot / step) * step, 2)


def _find_option(instruments_df: pd.DataFrame, name: str,
                 strike: float, opt_type: str, expiry: date) -> dict | None:
    """Find a specific option contract in the instruments list."""
    mask = (
        (instruments_df["name"] == name) &
        (instruments_df["strike"] == strike) &
        (instruments_df["instrument_type"] == opt_type) &
        (instruments_df["expiry"] == pd.Timestamp(expiry))
    )
    sub = instruments_df[mask]
    if sub.empty:
        return None
    return sub.iloc[0].to_dict()


class ShortStraddleStrategy(BaseStrategy):
    """
    Short Straddle — sell ATM Call + sell ATM Put.
    Profit: when underlying stays near the strike (low IV, rangebound).
    Loss:   when underlying moves sharply in either direction.

    Best used: before/after high-IV events (earnings, budget, RBI policy).
    """

    def __init__(
        self,
        underlying:   str,
        exchange:     str  = "NFO",
        quantity:     int  = 1,       # lots
        mode:         str  = "PAPER",
        strike_step:  float = 50.0,   # NIFTY=50, BANKNIFTY=100
        exit_before_expiry_days: int = 1,
    ):
        super().__init__(symbol=underlying, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.strike_step             = strike_step
        self.exit_before_expiry_days = exit_before_expiry_days
        self._entered = False
        self._expiry: date | None = None

    @property
    def name(self) -> str:
        return "SHORT_STRADDLE"

    @property
    def description(self) -> str:
        return f"Short Straddle on {self.symbol} — sell ATM CE + PE for premium income"

    def on_start(self) -> None:
        """Load instrument data on startup."""
        try:
            import kite_data as kd
            kite = kd.kite_client()
            instr = kite.instruments("NFO")
            self._instruments = pd.DataFrame(instr)
            self._instruments["expiry"] = pd.to_datetime(self._instruments["expiry"])
            print(f"[{self.name}] Instruments loaded — {len(self._instruments)} NFO contracts")
        except Exception as e:
            print(f"[{self.name}] Could not load instruments: {e}")
            self._instruments = pd.DataFrame()

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        spot = tick.get("last_price", 0)
        if not spot or self._instruments is None:
            return None

        now = datetime.now()

        # Exit if near expiry
        if self._entered and self._expiry:
            days_to_expiry = (self._expiry - now.date()).days
            if days_to_expiry <= self.exit_before_expiry_days:
                self._entered = False
                return self._make_signal(
                    action = "EXIT",
                    price  = spot,
                    reason = f"Expiry approaching ({days_to_expiry} days left)",
                )

        if self._entered:
            return None

        # Find nearest expiry
        future = self._instruments[
            (self._instruments["name"] == self.symbol.upper()) &
            (self._instruments["expiry"] >= pd.Timestamp.now())
        ]["expiry"].unique()

        if len(future) == 0:
            return None

        nearest_expiry = pd.Timestamp(sorted(future)[0]).date()
        atm_strike     = _get_atm_strike(spot, self.strike_step)

        # Find ATM CE and PE
        ce = _find_option(self._instruments, self.symbol.upper(),
                          atm_strike, "CE", nearest_expiry)
        pe = _find_option(self._instruments, self.symbol.upper(),
                          atm_strike, "PE", nearest_expiry)

        if not ce or not pe:
            return None

        self._entered = True
        self._expiry  = nearest_expiry

        return self._make_signal(
            action = "SELL",
            price  = spot,
            reason = f"Short Straddle — sell {atm_strike} CE + PE (expiry {nearest_expiry})",
            meta   = {
                "strategy":      "short_straddle",
                "atm_strike":    atm_strike,
                "ce_token":      ce["instrument_token"],
                "pe_token":      pe["instrument_token"],
                "ce_symbol":     ce["tradingsymbol"],
                "pe_symbol":     pe["tradingsymbol"],
                "expiry":        str(nearest_expiry),
            },
        )


class ShortStrangleStrategy(BaseStrategy):
    """
    Short Strangle — sell OTM Call + sell OTM Put.
    Wider breakeven than straddle, lower premium collected.
    Best for: high-IV environments, expecting range-bound movement.
    """

    def __init__(
        self,
        underlying:     str,
        exchange:       str   = "NFO",
        quantity:       int   = 1,
        mode:           str   = "PAPER",
        strike_step:    float = 50.0,
        otm_distance:   int   = 2,     # number of strikes away from ATM
        exit_before_expiry_days: int = 1,
    ):
        super().__init__(symbol=underlying, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.strike_step             = strike_step
        self.otm_distance            = otm_distance
        self.exit_before_expiry_days = exit_before_expiry_days
        self._entered    = False
        self._expiry: date | None = None
        self._instruments = None

    @property
    def name(self) -> str:
        return f"SHORT_STRANGLE_{self.otm_distance}x"

    @property
    def description(self) -> str:
        return (
            f"Short Strangle on {self.symbol} — sell OTM CE + PE "
            f"({self.otm_distance} strikes away from ATM)"
        )

    def on_start(self) -> None:
        try:
            import kite_data as kd
            instr = kd.kite_client().instruments("NFO")
            self._instruments = pd.DataFrame(instr)
            self._instruments["expiry"] = pd.to_datetime(self._instruments["expiry"])
        except Exception as e:
            print(f"[{self.name}] Instrument load failed: {e}")
            self._instruments = pd.DataFrame()

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        spot = tick.get("last_price", 0)
        if not spot or self._instruments is None or self._instruments.empty:
            return None

        now = datetime.now()

        if self._entered and self._expiry:
            days_to_expiry = (self._expiry - now.date()).days
            if days_to_expiry <= self.exit_before_expiry_days:
                self._entered = False
                return self._make_signal(
                    action = "EXIT",
                    price  = spot,
                    reason = f"Expiry in {days_to_expiry} days — closing strangle",
                )

        if self._entered:
            return None

        future = self._instruments[
            (self._instruments["name"] == self.symbol.upper()) &
            (self._instruments["expiry"] >= pd.Timestamp.now())
        ]["expiry"].unique()

        if len(future) == 0:
            return None

        nearest_expiry = pd.Timestamp(sorted(future)[0]).date()
        atm_strike     = _get_atm_strike(spot, self.strike_step)
        otm_call_strike = atm_strike + self.otm_distance * self.strike_step
        otm_put_strike  = atm_strike - self.otm_distance * self.strike_step

        ce = _find_option(self._instruments, self.symbol.upper(),
                          otm_call_strike, "CE", nearest_expiry)
        pe = _find_option(self._instruments, self.symbol.upper(),
                          otm_put_strike,  "PE", nearest_expiry)

        if not ce or not pe:
            return None

        self._entered = True
        self._expiry  = nearest_expiry

        return self._make_signal(
            action = "SELL",
            price  = spot,
            reason = (
                f"Short Strangle — sell {otm_call_strike} CE + {otm_put_strike} PE "
                f"(expiry {nearest_expiry})"
            ),
            meta = {
                "strategy":         "short_strangle",
                "atm_strike":       atm_strike,
                "ce_strike":        otm_call_strike,
                "pe_strike":        otm_put_strike,
                "ce_token":         ce["instrument_token"],
                "pe_token":         pe["instrument_token"],
                "ce_symbol":        ce["tradingsymbol"],
                "pe_symbol":        pe["tradingsymbol"],
                "expiry":           str(nearest_expiry),
            },
        )


class LongStraddleStrategy(BaseStrategy):
    """
    Long Straddle — buy ATM Call + buy ATM Put.
    Profit: when underlying makes a big move in either direction.
    Loss:   when underlying stays flat (time decay kills premium).
    Best for: before high-impact events (RBI, budget, earnings).
    """

    def __init__(
        self,
        underlying:   str,
        exchange:     str   = "NFO",
        quantity:     int   = 1,
        mode:         str   = "PAPER",
        strike_step:  float = 50.0,
        exit_before_expiry_days: int = 2,
    ):
        super().__init__(symbol=underlying, exchange=exchange,
                         quantity=quantity, mode=mode)
        self.strike_step             = strike_step
        self.exit_before_expiry_days = exit_before_expiry_days
        self._entered    = False
        self._expiry: date | None = None
        self._instruments = None

    @property
    def name(self) -> str:
        return "LONG_STRADDLE"

    @property
    def description(self) -> str:
        return f"Long Straddle on {self.symbol} — buy ATM CE + PE for big move"

    def on_start(self) -> None:
        try:
            import kite_data as kd
            instr = kd.kite_client().instruments("NFO")
            self._instruments = pd.DataFrame(instr)
            self._instruments["expiry"] = pd.to_datetime(self._instruments["expiry"])
        except Exception as e:
            self._instruments = pd.DataFrame()

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        spot = tick.get("last_price", 0)
        if not spot or self._instruments is None or self._instruments.empty:
            return None

        if self._entered and self._expiry:
            days_to_expiry = (self._expiry - datetime.now().date()).days
            if days_to_expiry <= self.exit_before_expiry_days:
                self._entered = False
                return self._make_signal(
                    action = "EXIT",
                    price  = spot,
                    reason = f"Expiry in {days_to_expiry} days — closing long straddle",
                )

        if self._entered:
            return None

        future = self._instruments[
            (self._instruments["name"] == self.symbol.upper()) &
            (self._instruments["expiry"] >= pd.Timestamp.now())
        ]["expiry"].unique()

        if len(future) == 0:
            return None

        nearest_expiry = pd.Timestamp(sorted(future)[0]).date()
        atm_strike     = _get_atm_strike(spot, self.strike_step)
        ce = _find_option(self._instruments, self.symbol.upper(),
                          atm_strike, "CE", nearest_expiry)
        pe = _find_option(self._instruments, self.symbol.upper(),
                          atm_strike, "PE", nearest_expiry)

        if not ce or not pe:
            return None

        self._entered = True
        self._expiry  = nearest_expiry

        return self._make_signal(
            action = "BUY",
            price  = spot,
            reason = f"Long Straddle — buy {atm_strike} CE + PE (expiry {nearest_expiry})",
            meta = {
                "strategy":   "long_straddle",
                "atm_strike": atm_strike,
                "ce_token":   ce["instrument_token"],
                "pe_token":   pe["instrument_token"],
                "ce_symbol":  ce["tradingsymbol"],
                "pe_symbol":  pe["tradingsymbol"],
                "expiry":     str(nearest_expiry),
            },
        )
