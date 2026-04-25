"""
Position Sizer
==============
Calculates optimal trade quantity based on account capital and risk rules.

Methods:
    fixed_risk()   — risk a fixed ₹ amount per trade
    pct_capital()  — risk a % of total capital per trade
    kelly()        — Kelly Criterion (optimal bet sizing)
    fixed_qty()    — always use a fixed quantity (simple)

Usage:
    ps = PositionSizer(capital=100000)
    qty = ps.fixed_risk(entry=2500, sl=2475, risk_per_trade=1000)
    # → risks ₹1000 on this trade, SL is ₹25 away → qty = 40
"""

from __future__ import annotations

import math


class PositionSizer:

    def __init__(self, capital: float, max_position_pct: float = 20.0):
        """
        capital          : total trading capital in ₹
        max_position_pct : max % of capital in any single position (default 20%)
        """
        self.capital          = capital
        self.max_position_pct = max_position_pct

    # ── Core methods ──────────────────────────────────────────────────────────

    def fixed_risk(
        self,
        entry:          float,
        sl:             float,
        risk_per_trade: float,
        lot_size:       int = 1,
    ) -> int:
        """
        Risk a fixed ₹ amount per trade.
        qty = risk_per_trade / |entry - sl|

        Example:
            entry=2500, sl=2475, risk=₹1000
            → risk per share = ₹25
            → qty = 1000/25 = 40 shares

        lot_size: round down to nearest lot (for F&O)
        """
        risk_per_unit = abs(entry - sl)
        if risk_per_unit <= 0:
            return 0

        raw_qty      = risk_per_trade / risk_per_unit
        max_qty      = (self.capital * self.max_position_pct / 100) / entry
        qty          = min(raw_qty, max_qty)

        if lot_size > 1:
            qty = math.floor(qty / lot_size) * lot_size
        else:
            qty = max(1, int(qty))

        return qty

    def pct_capital(
        self,
        entry:         float,
        risk_pct:      float = 1.0,
        sl:            float | None = None,
        lot_size:      int = 1,
    ) -> int:
        """
        Risk a % of capital per trade.
        If sl provided: uses fixed_risk() with risk_amt = capital * risk_pct/100
        If no sl: positions size = capital * risk_pct/100 / entry

        risk_pct: % of capital to risk (default 1%)
        """
        risk_amt = self.capital * risk_pct / 100

        if sl is not None:
            return self.fixed_risk(entry=entry, sl=sl,
                                   risk_per_trade=risk_amt, lot_size=lot_size)

        raw_qty = risk_amt / entry
        max_qty = (self.capital * self.max_position_pct / 100) / entry
        qty     = min(raw_qty, max_qty)

        if lot_size > 1:
            return max(lot_size, math.floor(qty / lot_size) * lot_size)
        return max(1, int(qty))

    def kelly(
        self,
        entry:      float,
        win_rate:   float,
        avg_win:    float,
        avg_loss:   float,
        fraction:   float = 0.25,
        lot_size:   int   = 1,
    ) -> int:
        """
        Kelly Criterion — mathematically optimal bet size.
        fraction: use only this fraction of Kelly (0.25 = quarter-Kelly, safer)

        kelly_pct = win_rate - (1 - win_rate) / (avg_win / avg_loss)
        position  = capital * kelly_pct * fraction / entry

        Example: win_rate=60%, avg_win=₹500, avg_loss=₹300
            kelly = 0.6 - 0.4/(500/300) = 0.6 - 0.24 = 0.36 → 36% of capital
            quarter-kelly = 9% of capital
        """
        if avg_loss <= 0 or avg_win <= 0:
            return 0

        b          = avg_win / avg_loss
        kelly_pct  = win_rate - (1 - win_rate) / b
        kelly_pct  = max(0, kelly_pct) * fraction

        # Cap at max_position_pct
        kelly_pct  = min(kelly_pct, self.max_position_pct / 100)

        invest_amt = self.capital * kelly_pct
        qty        = invest_amt / entry

        if lot_size > 1:
            return max(lot_size, math.floor(qty / lot_size) * lot_size)
        return max(1, int(qty))

    def fixed_qty(self, qty: int, lot_size: int = 1) -> int:
        """Always return a fixed quantity. Simplest approach."""
        if lot_size > 1:
            return max(lot_size, math.floor(qty / lot_size) * lot_size)
        return max(1, qty)

    # ── Summary ───────────────────────────────────────────────────────────────

    def explain(
        self,
        entry:          float,
        sl:             float,
        risk_per_trade: float,
    ) -> dict:
        """Show breakdown of a fixed_risk calculation."""
        risk_per_unit = abs(entry - sl)
        qty           = self.fixed_risk(entry=entry, sl=sl,
                                        risk_per_trade=risk_per_trade)
        return {
            "entry":          entry,
            "sl":             sl,
            "risk_per_unit":  round(risk_per_unit, 2),
            "risk_per_trade": risk_per_trade,
            "qty":            qty,
            "total_value":    round(qty * entry, 2),
            "max_loss":       round(qty * risk_per_unit, 2),
            "capital_used_%": round(qty * entry / self.capital * 100, 2),
        }
