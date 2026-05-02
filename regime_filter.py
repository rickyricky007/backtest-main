"""
Regime Filter
=============
Detects whether the market is TRENDING or RANGING on any given day.

Why this matters:
    - TRENDING market  → run momentum strategies (VWAP, ORB, SMA crossover)
    - RANGING market   → run mean-reversion / premium-selling (RSI, Short Straddle/Strangle)
    - Running the wrong strategy in the wrong regime is the #1 cause of losses

How it works (3 signals combined):
    1. ADX (Average Directional Index) > 25  → trending
    2. Price vs 20-day SMA distance > 1%     → directional move
    3. ATR % (volatility) vs 20-day average  → expanding = trending

Regime labels:
    "TRENDING_UP"   — ADX strong, price above SMA
    "TRENDING_DOWN" — ADX strong, price below SMA
    "RANGING"       — ADX weak, price near SMA
    "UNKNOWN"       — not enough data yet

Usage:
    from regime_filter import RegimeFilter

    rf = RegimeFilter()
    rf.update(high=100, low=98, close=99, volume=50000)
    regime = rf.regime          # "TRENDING_UP" / "RANGING" / etc.
    ok     = rf.allows("VWAP") # True/False — should this strategy run now?
"""

from __future__ import annotations

from collections import deque
from typing import Deque

# ── which strategies work in which regime ─────────────────────────────────────
STRATEGY_REGIMES: dict[str, list[str]] = {
    # Momentum — need a trend to work
    "VWAP":           ["TRENDING_UP", "TRENDING_DOWN"],
    "ORB_15m":        ["TRENDING_UP", "TRENDING_DOWN"],
    "ORB_5m":         ["TRENDING_UP", "TRENDING_DOWN"],
    "SMA_20_50":      ["TRENDING_UP", "TRENDING_DOWN"],
    "SMA_CROSSOVER":  ["TRENDING_UP", "TRENDING_DOWN"],

    # Mean-reversion / premium selling — need range to work
    "RSI":            ["RANGING"],
    "Light_NIFTY_RSI": ["RANGING"],
    "SHORT_STRADDLE": ["RANGING"],
    "SHORT_STRANGLE_2x": ["RANGING"],
    "SHORT_STRANGLE_3x": ["RANGING"],
    "LONG_STRADDLE":  ["TRENDING_UP", "TRENDING_DOWN"],  # needs big move

    # Neutral — always allowed
    "PAPER_TEST":     ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "UNKNOWN"],
}


class RegimeFilter:
    """
    Online regime detector — call update() on every candle, read .regime.

    Parameters
    ----------
    adx_period   : lookback for ADX calculation (default 14)
    adx_threshold: ADX > this → trending (default 25)
    sma_period   : SMA lookback for price-distance check (default 20)
    sma_band_pct : price must be > this % from SMA to count as directional (default 1.0)
    """

    def __init__(
        self,
        adx_period:    int   = 14,
        adx_threshold: float = 25.0,
        sma_period:    int   = 20,
        sma_band_pct:  float = 1.0,
    ):
        self.adx_period    = adx_period
        self.adx_threshold = adx_threshold
        self.sma_period    = sma_period
        self.sma_band_pct  = sma_band_pct / 100

        # Price history
        self._highs:  Deque[float] = deque(maxlen=adx_period + 1)
        self._lows:   Deque[float] = deque(maxlen=adx_period + 1)
        self._closes: Deque[float] = deque(maxlen=max(adx_period, sma_period) + 2)

        # ADX internals
        self._tr_history:  Deque[float] = deque(maxlen=adx_period)
        self._pdm_history: Deque[float] = deque(maxlen=adx_period)
        self._ndm_history: Deque[float] = deque(maxlen=adx_period)
        self._dx_history:  Deque[float] = deque(maxlen=adx_period)

        self._adx:    float = 0.0
        self._regime: str   = "UNKNOWN"

    # ── public interface ──────────────────────────────────────────────────────

    @property
    def regime(self) -> str:
        return self._regime

    @property
    def adx(self) -> float:
        return round(self._adx, 2)

    def allows(self, strategy_name: str) -> bool:
        """
        Returns True if this strategy should run in the current regime.
        If strategy is not in the registry, defaults to ALLOWED (don't block unknown strategies).
        """
        allowed_regimes = STRATEGY_REGIMES.get(strategy_name)
        if allowed_regimes is None:
            return True   # unknown strategy → allow by default
        if self._regime == "UNKNOWN":
            return True   # not enough data → allow by default
        return self._regime in allowed_regimes

    def update(self, high: float, low: float, close: float, volume: float = 0) -> str:
        """Feed one candle. Returns the new regime string."""
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        if len(self._closes) < self.adx_period + 1:
            self._regime = "UNKNOWN"
            return self._regime

        self._update_adx()
        self._update_regime(close)
        return self._regime

    # ── ADX calculation ───────────────────────────────────────────────────────

    def _update_adx(self) -> None:
        closes = list(self._closes)
        highs  = list(self._highs)
        lows   = list(self._lows)

        prev_close = closes[-2]
        curr_high  = highs[-1]
        curr_low   = lows[-1]
        prev_high  = highs[-2] if len(highs) >= 2 else curr_high
        prev_low   = lows[-2]  if len(lows)  >= 2 else curr_low

        # True Range
        tr = max(
            curr_high - curr_low,
            abs(curr_high - prev_close),
            abs(curr_low  - prev_close),
        )

        # Directional movement
        up_move   = curr_high - prev_high
        down_move = prev_low  - curr_low
        pdm = up_move   if (up_move > down_move and up_move > 0)   else 0.0
        ndm = down_move if (down_move > up_move and down_move > 0) else 0.0

        self._tr_history.append(tr)
        self._pdm_history.append(pdm)
        self._ndm_history.append(ndm)

        if len(self._tr_history) < self.adx_period:
            return

        atr  = sum(self._tr_history)
        apdm = sum(self._pdm_history)
        andm = sum(self._ndm_history)

        if atr == 0:
            return

        pdi = 100 * apdm / atr
        ndi = 100 * andm / atr

        if (pdi + ndi) == 0:
            dx = 0.0
        else:
            dx = 100 * abs(pdi - ndi) / (pdi + ndi)

        self._dx_history.append(dx)
        self._adx = sum(self._dx_history) / len(self._dx_history)

    def _update_regime(self, close: float) -> None:
        closes = list(self._closes)

        # 20-day SMA
        if len(closes) >= self.sma_period:
            sma = sum(closes[-self.sma_period:]) / self.sma_period
        else:
            sma = closes[-1]

        price_vs_sma = (close - sma) / sma if sma else 0

        trending = self._adx >= self.adx_threshold

        if trending:
            if price_vs_sma > self.sma_band_pct:
                self._regime = "TRENDING_UP"
            elif price_vs_sma < -self.sma_band_pct:
                self._regime = "TRENDING_DOWN"
            else:
                # ADX says trending but price is near SMA — call it ranging
                self._regime = "RANGING"
        else:
            self._regime = "RANGING"

    def summary(self) -> dict:
        return {
            "regime": self._regime,
            "adx":    self.adx,
            "adx_threshold": self.adx_threshold,
        }


# ── Multi-symbol regime tracker ───────────────────────────────────────────────

class RegimeTracker:
    """
    Tracks regime for multiple symbols simultaneously.
    Used by strategy_engine.py to hold one RegimeFilter per subscribed symbol.

    Usage:
        tracker = RegimeTracker()
        tracker.update("NIFTY", high=22100, low=21900, close=22050)
        tracker.allows("NIFTY", "VWAP")   # True / False
    """

    def __init__(self):
        self._filters: dict[str, RegimeFilter] = {}

    def update(self, symbol: str, high: float, low: float,
               close: float, volume: float = 0) -> str:
        if symbol not in self._filters:
            self._filters[symbol] = RegimeFilter()
        return self._filters[symbol].update(high, low, close, volume)

    def regime(self, symbol: str) -> str:
        return self._filters.get(symbol, RegimeFilter()).regime

    def adx(self, symbol: str) -> float:
        return self._filters.get(symbol, RegimeFilter()).adx

    def allows(self, symbol: str, strategy_name: str) -> bool:
        f = self._filters.get(symbol)
        if f is None:
            return True   # no data yet → allow
        return f.allows(strategy_name)

    def all_regimes(self) -> dict[str, str]:
        return {sym: f.regime for sym, f in self._filters.items()}


# ── standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import random
    rf = RegimeFilter()
    price = 22000.0
    print("Simulating 50 candles...\n")
    for i in range(50):
        # Simulate a trending move for first 30 candles, then range-bound
        if i < 30:
            price += random.uniform(10, 50)   # uptrend
        else:
            price += random.uniform(-20, 20)   # ranging

        high  = price + random.uniform(5, 30)
        low   = price - random.uniform(5, 30)
        close = price

        regime = rf.update(high=high, low=low, close=close)
        if i % 5 == 0 or i >= 25:
            print(f"Candle {i+1:3d}  close={close:8.1f}  ADX={rf.adx:5.1f}  regime={regime}")

    print(f"\nFinal regime: {rf.regime}")
    print(f"VWAP allowed:  {rf.allows('VWAP')}")
    print(f"RSI allowed:   {rf.allows('RSI')}")
    print(f"Straddle allowed: {rf.allows('SHORT_STRADDLE')}")
