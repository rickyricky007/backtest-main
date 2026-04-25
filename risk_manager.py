"""
Risk Manager — Phase 2 Complete
================================
Guards every signal before it reaches the order manager.

Checks:
    - Max daily loss limit
    - Max open positions
    - Max orders per day
    - Trading hours (market only)
    - Duplicate signal prevention
    - Position sizing (via PositionSizer)
    - Greeks risk limits (for F&O — delta, theta, vega)
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import TYPE_CHECKING

from position_sizer import PositionSizer

if TYPE_CHECKING:
    from strategies.base_strategy import Signal


class RiskManager:

    def __init__(
        self,
        capital:        float = 100_000.0,  # ₹ total trading capital
        max_daily_loss: float = 5_000.0,    # ₹ stop all trading if hit
        max_positions:  int   = 5,
        max_orders_day: int   = 20,
        risk_per_trade: float = 1.0,        # % of capital to risk per trade
        market_open:    dtime = dtime(9, 15),
        market_close:   dtime = dtime(15, 25),
        allow_exit_after: bool = True,
        # Greeks limits (F&O)
        max_delta:      float = 500.0,      # max net delta exposure
        max_theta:      float = -2000.0,    # max daily theta decay (₹)
        max_vega:       float = 1000.0,     # max vega exposure
    ):
        self.capital          = capital
        self.max_daily_loss   = max_daily_loss
        self.max_positions    = max_positions
        self.max_orders_day   = max_orders_day
        self.risk_per_trade   = risk_per_trade
        self.market_open      = market_open
        self.market_close     = market_close
        self.allow_exit_after = allow_exit_after
        self.max_delta        = max_delta
        self.max_theta        = max_theta
        self.max_vega         = max_vega

        # Position sizer
        self.sizer = PositionSizer(capital=capital)

        # Runtime state — resets each day
        self._daily_pnl:      float    = 0.0
        self._order_count:    int      = 0
        self._open_positions: set[str] = set()
        self._signal_keys:    set[str] = set()
        self._last_reset:     str      = ""

        # Greeks tracking
        self._net_delta: float = 0.0
        self._net_theta: float = 0.0
        self._net_vega:  float = 0.0

    # ── Daily reset ───────────────────────────────────────────────────────────

    def _maybe_reset(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_reset:
            self._daily_pnl    = 0.0
            self._order_count  = 0
            self._signal_keys  = set()
            self._last_reset   = today
            print(f"[RiskManager] Daily reset for {today}")

    # ── Main gate ─────────────────────────────────────────────────────────────

    def approve(self, signal: "Signal") -> tuple[bool, str]:
        """
        Returns (approved, reason).
        Call before placing any order.
        """
        self._maybe_reset()
        now = datetime.now().time()

        # EXIT signals always pass (must be able to close positions)
        if signal.action in ("EXIT", "EXIT_SHORT") and self.allow_exit_after:
            return True, "EXIT — always approved"

        # Market hours
        if not (self.market_open <= now <= self.market_close):
            return False, f"Outside market hours ({self.market_open}–{self.market_close})"

        # Daily loss limit
        if self._daily_pnl <= -abs(self.max_daily_loss):
            return False, f"Daily loss limit hit (₹{self._daily_pnl:,.0f}). No more trades today."

        # Max orders
        if self._order_count >= self.max_orders_day:
            return False, f"Max orders/day reached ({self.max_orders_day})"

        # Max positions
        if (
            signal.action in ("BUY", "SELL")
            and signal.symbol not in self._open_positions
            and len(self._open_positions) >= self.max_positions
        ):
            return False, f"Max open positions reached ({self.max_positions})"

        # Duplicate signal (same strategy+symbol+action within same minute)
        key = f"{signal.strategy}_{signal.symbol}_{signal.action}_{datetime.now().strftime('%Y%m%d%H%M')}"
        if key in self._signal_keys:
            return False, "Duplicate signal — already fired this minute"
        self._signal_keys.add(key)

        # Greeks check (for F&O signals)
        greeks = signal.meta.get("greeks", {})
        if greeks:
            approved, reason = self._check_greeks(greeks, signal.action)
            if not approved:
                return False, reason

        return True, "Approved"

    # ── Position sizing ───────────────────────────────────────────────────────

    def size(
        self,
        signal:   "Signal",
        sl_price: float | None = None,
        method:   str          = "fixed_risk",
        lot_size: int          = 1,
    ) -> int:
        """
        Calculate optimal quantity for a signal.

        method:
            "fixed_risk" — risk_per_trade % of capital, sized by SL distance
            "pct"        — buy risk_per_trade % of capital worth
            "fixed"      — use signal.quantity as-is
        """
        if method == "fixed_risk" and sl_price:
            return self.sizer.fixed_risk(
                entry          = signal.price,
                sl             = sl_price,
                risk_per_trade = self.capital * self.risk_per_trade / 100,
                lot_size       = lot_size,
            )
        elif method == "pct":
            return self.sizer.pct_capital(
                entry    = signal.price,
                risk_pct = self.risk_per_trade,
                lot_size = lot_size,
            )
        return signal.quantity  # fallback: use strategy's default qty

    # ── Greeks risk (F&O) ─────────────────────────────────────────────────────

    def update_greeks(self, delta: float, theta: float, vega: float) -> None:
        """Call after each F&O order to track portfolio Greeks."""
        self._net_delta += delta
        self._net_theta += theta
        self._net_vega  += vega

    def _check_greeks(self, greeks: dict, action: str) -> tuple[bool, str]:
        """Check if adding this position keeps Greeks within limits."""
        new_delta = self._net_delta + greeks.get("delta", 0)
        new_theta = self._net_theta + greeks.get("theta", 0)
        new_vega  = self._net_vega  + greeks.get("vega",  0)

        if abs(new_delta) > self.max_delta:
            return False, f"Delta limit breach: {new_delta:.0f} > {self.max_delta}"
        if new_theta < self.max_theta:
            return False, f"Theta decay too high: ₹{new_theta:.0f}/day > limit ₹{self.max_theta}"
        if abs(new_vega) > self.max_vega:
            return False, f"Vega exposure too high: {new_vega:.0f} > {self.max_vega}"

        return True, "Greeks within limits"

    def greeks_status(self) -> dict:
        return {
            "net_delta": round(self._net_delta, 2),
            "net_theta": round(self._net_theta, 2),
            "net_vega":  round(self._net_vega,  2),
            "limits":    {
                "max_delta": self.max_delta,
                "max_theta": self.max_theta,
                "max_vega":  self.max_vega,
            },
        }

    # ── State updates ─────────────────────────────────────────────────────────

    def on_order_placed(self, signal: "Signal") -> None:
        self._order_count += 1
        if signal.action in ("BUY", "SELL"):
            self._open_positions.add(signal.symbol)
        elif signal.action in ("EXIT", "EXIT_SHORT"):
            self._open_positions.discard(signal.symbol)

    def on_pnl_update(self, pnl_delta: float) -> None:
        self._daily_pnl += pnl_delta
        print(f"[RiskManager] Daily P&L updated: ₹{self._daily_pnl:+,.0f}")

    # ── Full status ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "capital":         self.capital,
            "daily_pnl":       round(self._daily_pnl, 2),
            "daily_pnl_%":     round(self._daily_pnl / self.capital * 100, 2),
            "orders_today":    self._order_count,
            "open_positions":  list(self._open_positions),
            "loss_limit_hit":  self._daily_pnl <= -abs(self.max_daily_loss),
            "greeks":          self.greeks_status(),
        }
