"""
BaseStrategy — template every strategy must follow.

To create a new strategy:
    1. Create a new file in strategies/
    2. Inherit from BaseStrategy
    3. Implement on_tick() — return a Signal or None
    4. Register it in strategy_engine.py

That's it. No other file needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Signal:
    """Represents a trade signal emitted by a strategy."""

    strategy:  str            # strategy name e.g. "RSI"
    symbol:    str            # trading symbol e.g. "RELIANCE"
    exchange:  str            # "NSE" or "BSE"
    action:    str            # "BUY", "SELL", or "EXIT"
    quantity:  int            # number of shares/lots
    price:     float          # price at signal time
    reason:    str            # human-readable reason e.g. "RSI crossed below 30"
    timestamp: datetime = field(default_factory=datetime.now)
    meta:      dict = field(default_factory=dict)  # any extra data (RSI value, etc.)

    def __str__(self) -> str:
        return (
            f"[{self.timestamp.strftime('%H:%M:%S')}] {self.strategy} | "
            f"{self.action} {self.quantity} {self.symbol} @ ₹{self.price:.2f} | {self.reason}"
        )


class BaseStrategy(ABC):
    """
    Abstract base class for all strategies.

    Subclasses MUST implement:
        - name         (property) — unique strategy identifier
        - description  (property) — what the strategy does
        - on_tick()    — called on every live tick, return Signal or None

    Subclasses MAY override:
        - on_start()   — called once when engine starts
        - on_stop()    — called when engine stops
        - on_candle()  — called when a new candle closes (optional)
    """

    def __init__(
        self,
        symbol:    str,
        exchange:  str  = "NSE",
        quantity:  int  = 1,
        mode:      str  = "PAPER",   # "PAPER" or "LIVE"
        enabled:   bool = True,
    ):
        self.symbol   = symbol.upper()
        self.exchange = exchange.upper()
        self.quantity = quantity
        self.mode     = mode.upper()
        self.enabled  = enabled

        # Internal state — available to all strategies
        self._price_buffer: list[float] = []   # rolling close prices
        self._last_signal:  Signal | None = None
        self._signal_count: int = 0

    # ── Must implement ────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this strategy e.g. 'RSI_14'"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of what this strategy does."""
        ...

    @abstractmethod
    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        """
        Called on every live market tick.
        tick dict contains: instrument_token, last_price, ohlc, volume, etc.
        Return a Signal to place an order, or None to do nothing.
        """
        ...

    # ── May override ──────────────────────────────────────────────────────────

    def on_start(self) -> None:
        """Called once when the engine starts. Use for warm-up data loading."""
        pass

    def on_stop(self) -> None:
        """Called when the engine stops cleanly."""
        pass

    def on_candle(self, candle: dict[str, Any]) -> Signal | None:
        """Called when a new candle closes. Optional — override if needed."""
        return None

    # ── Helpers available to all strategies ───────────────────────────────────

    def _add_price(self, price: float, maxlen: int = 500) -> None:
        """Add a price to the rolling buffer. Keeps last `maxlen` prices."""
        self._price_buffer.append(price)
        if len(self._price_buffer) > maxlen:
            self._price_buffer.pop(0)

    def _make_signal(
        self,
        action:   str,
        price:    float,
        reason:   str,
        quantity: int | None = None,
        meta:     dict | None = None,
    ) -> Signal:
        """Convenience method to create a Signal with common fields filled."""
        self._signal_count += 1
        sig = Signal(
            strategy  = self.name,
            symbol    = self.symbol,
            exchange  = self.exchange,
            action    = action,
            quantity  = quantity or self.quantity,
            price     = price,
            reason    = reason,
            meta      = meta or {},
        )
        self._last_signal = sig
        return sig

    def __repr__(self) -> str:
        return f"<{self.name} symbol={self.symbol} mode={self.mode} enabled={self.enabled}>"
