"""
Stop Loss Manager
=================
Tracks open positions and manages:
    - Per-trade fixed stop loss
    - Trailing stop loss (moves up as price moves in your favour)
    - Target / take-profit levels

How it works:
    1. Register a position after entry → SLManager.register()
    2. Call SLManager.on_tick(tick) on every live tick
    3. It automatically fires an exit signal when SL or target is hit
    4. The strategy engine picks up the exit signal and places the order

Usage in strategy engine:
    from stop_loss_manager import StopLossManager
    slm = StopLossManager(order_manager)

    # After BUY signal fills:
    slm.register(
        symbol     = "RELIANCE",
        action     = "BUY",
        entry_price= 2500.0,
        qty        = 10,
        sl_points  = 25.0,     # ₹25 stop loss → SL at ₹2475
        target_pts = 50.0,     # ₹50 target → exit at ₹2550
        trailing_sl= 15.0,     # trail by ₹15 as price moves up
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from db import execute, init_tables
from logger import get_logger
from telegram import send_sl_hit

log = get_logger("stop_loss_manager")


@dataclass
class Position:
    """Represents one open position being tracked."""
    symbol:       str
    exchange:     str
    action:       str          # "BUY" or "SELL"
    qty:          int
    entry_price:  float
    sl_price:     float        # current stop-loss level
    target_price: float | None # take-profit level (None = no target)
    trailing_sl:  float        # trailing step in ₹ (0 = disabled)
    strategy:     str
    entry_time:   datetime = field(default_factory=datetime.now)
    peak_price:   float    = 0.0   # highest price seen since entry (for trailing)
    status:       str      = "OPEN"

    def __post_init__(self):
        self.peak_price = self.entry_price


class StopLossManager:
    """
    Monitors all open positions on every tick.
    Fires exit orders automatically when SL or target is hit.
    """

    def __init__(self, order_manager=None):
        """
        order_manager : OrderManager instance (optional)
                        If provided, exits are placed automatically.
                        If None, exits are only logged.
        """
        self._om         = order_manager
        self._positions: dict[str, Position] = {}  # symbol → Position
        init_tables()

    # ── Register a new position ───────────────────────────────────────────────

    def register(
        self,
        symbol:      str,
        action:      str,
        entry_price: float,
        qty:         int,
        sl_points:   float,
        target_pts:  float | None = None,
        trailing_sl: float        = 0.0,
        exchange:    str          = "NSE",
        strategy:    str          = "",
    ) -> Position:
        """
        Register a new open position for SL tracking.

        sl_points   : stop-loss distance in ₹ from entry
        target_pts  : take-profit distance in ₹ from entry (None = no target)
        trailing_sl : trail SL by this many ₹ as price moves in your favour
        """
        action = action.upper()

        if action == "BUY":
            sl_price     = round(entry_price - sl_points, 2)
            target_price = round(entry_price + target_pts, 2) if target_pts else None
        else:  # SELL / SHORT
            sl_price     = round(entry_price + sl_points, 2)
            target_price = round(entry_price - target_pts, 2) if target_pts else None

        pos = Position(
            symbol       = symbol.upper(),
            exchange     = exchange,
            action       = action,
            qty          = qty,
            entry_price  = entry_price,
            sl_price     = sl_price,
            target_price = target_price,
            trailing_sl  = trailing_sl,
            strategy     = strategy,
        )
        self._positions[symbol.upper()] = pos
        try:
            self._log_position(pos)
        except Exception:
            log.error("Failed to log position to DB", exc_info=True)

        log.info(
            f"Registered {action} {qty} {symbol} "
            f"entry=₹{entry_price} SL=₹{sl_price} "
            f"target={'₹'+str(target_price) if target_price else 'none'} "
            f"trailing={'₹'+str(trailing_sl) if trailing_sl else 'off'}"
        )
        return pos

    # ── Process every tick ────────────────────────────────────────────────────

    def on_tick(self, tick: dict[str, Any]) -> str | None:
        """
        Call this on every market tick.
        Returns exit reason string if an exit was triggered, else None.
        """
        try:
            symbol = None
            for key in ("tradingsymbol", "symbol"):
                symbol = tick.get(key)
                if symbol:
                    break

            if not symbol:
                return None

            symbol = symbol.upper()
            pos    = self._positions.get(symbol)

            if not pos or pos.status != "OPEN":
                return None

            price = tick.get("last_price") or tick.get("ltp")
            if not price:
                return None

            price = float(price)

            # ── Update trailing stop loss ─────────────────────────────────────
            if pos.trailing_sl > 0:
                if pos.action == "BUY" and price > pos.peak_price:
                    pos.peak_price = price
                    new_sl = round(pos.peak_price - pos.trailing_sl, 2)
                    if new_sl > pos.sl_price:
                        log.info(f"Trailing SL moved UP: {pos.symbol} SL ₹{pos.sl_price} → ₹{new_sl}")
                        pos.sl_price = new_sl

                elif pos.action == "SELL" and price < pos.peak_price:
                    pos.peak_price = price
                    new_sl = round(pos.peak_price + pos.trailing_sl, 2)
                    if new_sl < pos.sl_price:
                        log.info(f"Trailing SL moved DOWN: {pos.symbol} SL ₹{pos.sl_price} → ₹{new_sl}")
                        pos.sl_price = new_sl

            # ── Check stop loss ───────────────────────────────────────────────
            sl_hit = (
                (pos.action == "BUY"  and price <= pos.sl_price) or
                (pos.action == "SELL" and price >= pos.sl_price)
            )
            if sl_hit:
                reason = f"Stop loss hit @ ₹{price} (SL=₹{pos.sl_price})"
                self._exit(pos, price, reason)
                return reason

            # ── Check target ──────────────────────────────────────────────────
            if pos.target_price:
                target_hit = (
                    (pos.action == "BUY"  and price >= pos.target_price) or
                    (pos.action == "SELL" and price <= pos.target_price)
                )
                if target_hit:
                    reason = f"Target hit @ ₹{price} (target=₹{pos.target_price})"
                    self._exit(pos, price, reason)
                    return reason

            return None

        except Exception:
            log.error(f"on_tick error for {tick.get('symbol','?')}", exc_info=True)
            return None

    # ── Manual exit ───────────────────────────────────────────────────────────

    def exit_position(self, symbol: str, price: float, reason: str = "Manual exit") -> bool:
        """Manually exit a tracked position."""
        pos = self._positions.get(symbol.upper())
        if not pos or pos.status != "OPEN":
            return False
        self._exit(pos, price, reason)
        return True

    def remove(self, symbol: str) -> None:
        """Remove a position from tracking (e.g. already exited elsewhere)."""
        self._positions.pop(symbol.upper(), None)

    # ── Status & info ─────────────────────────────────────────────────────────

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.status == "OPEN"]

    def get_position(self, symbol: str) -> Position | None:
        return self._positions.get(symbol.upper())

    def summary(self) -> list[dict]:
        return [
            {
                "symbol":       p.symbol,
                "action":       p.action,
                "qty":          p.qty,
                "entry":        p.entry_price,
                "sl":           p.sl_price,
                "target":       p.target_price,
                "peak":         round(p.peak_price, 2),
                "trailing_sl":  p.trailing_sl,
                "status":       p.status,
            }
            for p in self._positions.values()
        ]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _exit(self, pos: Position, exit_price: float, reason: str) -> None:
        pos.status = "EXITED"

        if pos.action == "BUY":
            pnl = round((exit_price - pos.entry_price) * pos.qty, 2)
            exit_action = "SELL"
        else:
            pnl = round((pos.entry_price - exit_price) * pos.qty, 2)
            exit_action = "BUY"

        emoji = "✅" if pnl >= 0 else "❌"
        log.info(f"{emoji} EXIT {pos.symbol}: {reason} | P&L: ₹{pnl:+,.2f}")
        send_sl_hit(symbol=pos.symbol, trigger_price=exit_price, pnl=pnl)

        # Place exit order via OrderManager
        if self._om:
            try:
                self._om.market(
                    symbol   = pos.symbol,
                    action   = exit_action,
                    qty      = pos.qty,
                    exchange = pos.exchange,
                    strategy = pos.strategy,
                    reason   = reason,
                    meta     = {"pnl": pnl, "exit_reason": reason},
                )
            except Exception:
                log.error(f"Failed to place exit order for {pos.symbol}", exc_info=True)

        # Update DB
        try:
            execute("""
                UPDATE sl_positions
                SET status='EXITED'
                WHERE symbol=%s AND status='OPEN'
            """, (pos.symbol,))
        except Exception:
            log.error(f"Failed to update DB for exit {pos.symbol}", exc_info=True)

    def _log_position(self, pos: Position) -> None:
        execute("""
            INSERT INTO sl_positions
                (symbol, exchange, action, qty, entry_price,
                 sl_price, target_price, trailing_sl, status, strategy, entry_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            pos.symbol, pos.exchange, pos.action, pos.qty, pos.entry_price,
            pos.sl_price, pos.target_price, pos.trailing_sl,
            "OPEN", pos.strategy,
            pos.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
        ))
