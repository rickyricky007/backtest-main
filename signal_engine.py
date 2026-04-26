"""
Signal Engine — Multi-Symbol Confluence Scanner
================================================
Scans ALL F&O symbols using the 10-indicator weighted scoring system.
Generates BUY/SELL signals when confluence threshold is met.
Routes signals through RiskManager → OrderManager → Kite (paper or live).

Flow:
    1. Fetch OHLCV for each symbol (Kite if live, yfinance fallback)
    2. Run score_symbol() — all 10 indicators
    3. If score >= BUY_THRESHOLD  → BUY signal
    4. If score <= SELL_THRESHOLD → SELL signal
    5. RiskManager.approve()      → check daily loss / position limits
    6. OrderManager.market()      → paper log OR real Kite order

Usage:
    engine = SignalEngine(mode="PAPER")
    results = engine.scan_all()          # scan everything, return scores
    engine.scan_and_trade()              # scan + auto-execute signals

    # Run as continuous loop:
    engine.run_loop(interval_seconds=300)  # scan every 5 minutes
"""

from __future__ import annotations

import time
from datetime import datetime, date
from typing import Any

import numpy as np

from fo_symbols import (
    ALL_FO_SYMBOLS, FO_INDICES, FO_STOCKS, TOP_50_LIQUID,
    get_yf_ticker, is_index,
)
from indicators import score_symbol, score_summary, BUY_THRESHOLD, SELL_THRESHOLD
from logger import get_logger
from risk_manager import RiskManager
from order_manager import OrderManager
from telegram import send_signal

log = get_logger("signal_engine")

# ── Default scan universe ─────────────────────────────────────────────────────
# Change to ALL_FO_SYMBOLS for full scan (slower)
# Use TOP_50_LIQUID for fast scans during testing
DEFAULT_SYMBOLS = list(FO_INDICES.keys()) + TOP_50_LIQUID


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHER
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_ohlcv(symbol: str, interval: str = "15m", days: int = 5) -> dict | None:
    """
    Fetch OHLCV data for a symbol.
    Returns dict with keys: closes, highs, lows, volumes
    Returns None if data unavailable.
    """
    try:
        import yfinance as yf
        ticker = get_yf_ticker(symbol)
        df = yf.Ticker(ticker).history(period=f"{days}d", interval=interval)

        if df.empty or len(df) < 30:
            return None

        # Flatten multi-level columns if present
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)

        return {
            "closes":  df["Close"].dropna().tolist(),
            "highs":   df["High"].dropna().tolist(),
            "lows":    df["Low"].dropna().tolist(),
            "volumes": df["Volume"].dropna().tolist(),
        }

    except Exception:
        log.warning(f"Failed to fetch OHLCV for {symbol}", exc_info=False)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class SignalEngine:
    """
    Scans F&O symbols and executes trades based on confluence scoring.

    Parameters
    ----------
    mode        : "PAPER" or "LIVE"
    symbols     : list of symbols to scan (default = indices + top 50 liquid)
    capital     : trading capital for risk sizing
    scan_interval: seconds between scans in run_loop()
    min_score   : minimum absolute score to act on (default = BUY_THRESHOLD)
    """

    def __init__(
        self,
        mode:          str        = "PAPER",
        symbols:       list[str]  | None = None,
        capital:       float      = 100_000.0,
        scan_interval: int        = 300,       # 5 minutes
        quantity:      int        = 1,
    ):
        self.mode          = mode.upper()
        self.symbols       = symbols or DEFAULT_SYMBOLS
        self.capital       = capital
        self.scan_interval = scan_interval
        self.quantity      = quantity

        # Sub-systems
        self._risk = RiskManager(capital=capital)
        self._om   = OrderManager()

        # State
        self._last_scan:    datetime | None = None
        self._scan_count:   int             = 0
        self._signal_count: int             = 0

        log.info(
            f"SignalEngine initialised | mode={self.mode} | "
            f"symbols={len(self.symbols)} | interval={scan_interval}s"
        )

    # ── Switch mode on the fly ────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """Switch between PAPER and LIVE without restarting."""
        prev = self.mode
        self.mode = mode.upper()
        log.info(f"Mode switched: {prev} → {self.mode}")

    # ── Scan a single symbol ──────────────────────────────────────────────────

    def scan_symbol(self, symbol: str) -> dict[str, Any]:
        """
        Fetch data + score a single symbol.
        Returns full result dict including score, action, signals breakdown.
        """
        result = {
            "symbol":    symbol,
            "action":    "WAIT",
            "score":     0,
            "pct":       0.0,
            "signals":   [],
            "price":     None,
            "error":     None,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }

        try:
            data = _fetch_ohlcv(symbol)
            if not data:
                result["error"] = "No data"
                return result

            closes  = data["closes"]
            highs   = data["highs"]
            lows    = data["lows"]
            volumes = data["volumes"]

            # Align lengths
            min_len = min(len(closes), len(highs), len(lows), len(volumes))
            if min_len < 30:
                result["error"] = "Insufficient data"
                return result

            closes  = closes[-min_len:]
            highs   = highs[-min_len:]
            lows    = lows[-min_len:]
            volumes = volumes[-min_len:]

            scored = score_symbol(closes, highs, lows, volumes)

            result.update({
                "action":  scored["action"],
                "score":   scored["score"],
                "pct":     scored["pct"],
                "signals": scored["signals"],
                "price":   round(closes[-1], 2),
            })

            log.debug(f"{symbol}: {score_summary(scored)}")

        except Exception:
            result["error"] = "Scan error"
            log.error(f"scan_symbol failed for {symbol}", exc_info=True)

        return result

    # ── Scan all symbols ──────────────────────────────────────────────────────

    def scan_all(self, symbols: list[str] | None = None) -> list[dict]:
        """
        Scan all symbols and return scored results sorted by score descending.
        Does NOT execute any trades — just returns scores.
        """
        symbols = symbols or self.symbols
        results = []

        log.info(f"Scanning {len(symbols)} symbols...")
        for symbol in symbols:
            result = self.scan_symbol(symbol)
            results.append(result)

        # Sort: strongest BUY first, then WAIT, then strongest SELL
        results.sort(key=lambda r: r["score"], reverse=True)
        self._last_scan    = datetime.now()
        self._scan_count  += 1

        buy_count  = sum(1 for r in results if r["action"] == "BUY")
        sell_count = sum(1 for r in results if r["action"] == "SELL")
        log.info(f"Scan complete — BUY: {buy_count} | SELL: {sell_count} | WAIT: {len(results)-buy_count-sell_count}")

        return results

    # ── Scan + execute trades ─────────────────────────────────────────────────

    def scan_and_trade(self, symbols: list[str] | None = None) -> list[dict]:
        """
        Full pipeline: scan all symbols → filter signals → risk check → execute.
        Returns list of signals that were acted on.
        """
        results  = self.scan_all(symbols)
        executed = []

        for r in results:
            if r["action"] not in ("BUY", "SELL"):
                continue
            if r.get("error"):
                continue
            if not r.get("price"):
                continue

            try:
                # Build a minimal signal object for RiskManager
                signal = _make_signal(
                    symbol   = r["symbol"],
                    action   = r["action"],
                    price    = r["price"],
                    quantity = self.quantity,
                    score    = r["score"],
                    mode     = self.mode,
                )

                approved, reason = self._risk.approve(signal)
                if not approved:
                    log.info(f"Signal blocked [{r['symbol']} {r['action']}]: {reason}")
                    continue

                # Execute via OrderManager
                order_result = self._om.market(
                    symbol   = r["symbol"],
                    action   = r["action"],
                    qty      = self.quantity,
                    exchange = "NSE",
                    strategy = f"ScoreEngine({r['score']:+d})",
                    mode     = self.mode,
                    meta     = {
                        "score":    r["score"],
                        "pct":      r["pct"],
                        "signals":  r["signals"],
                    },
                )

                self._risk.on_order_placed(signal)
                self._signal_count += 1

                executed.append({
                    **r,
                    "order_result": order_result,
                    "mode":         self.mode,
                })

                log.info(
                    f"{'📄 PAPER' if self.mode == 'PAPER' else '🔴 LIVE'} "
                    f"{r['action']} {r['symbol']} @ ₹{r['price']} "
                    f"| Score: {r['score']:+d} | {reason}"
                )

                # Telegram alert — only for LIVE mode to avoid spam in PAPER
                if self.mode == "LIVE":
                    send_signal(
                        symbol=r["symbol"],
                        action=r["action"],
                        score=r["score"],
                        price=r["price"],
                        mode=self.mode,
                    )

            except Exception:
                log.error(f"Failed to execute signal for {r['symbol']}", exc_info=True)

        return executed

    # ── Continuous loop ───────────────────────────────────────────────────────

    def run_loop(self, symbols: list[str] | None = None) -> None:
        """
        Run scan_and_trade() continuously at self.scan_interval seconds.
        Stops outside market hours automatically.
        Press Ctrl+C to stop.
        """
        log.info(f"Signal engine loop started | mode={self.mode} | interval={self.scan_interval}s")
        log.info("Press Ctrl+C to stop.")

        try:
            while True:
                now = datetime.now().time()

                # Only scan during market hours (9:15 to 15:30 IST)
                market_open  = now >= __import__("datetime").time(9, 15)
                market_close = now <= __import__("datetime").time(15, 30)

                if not market_open or not market_close:
                    log.info("Market closed — sleeping 5 minutes...")
                    time.sleep(300)
                    continue

                # Skip weekends
                if date.today().weekday() >= 5:
                    log.info("Weekend — sleeping 1 hour...")
                    time.sleep(3600)
                    continue

                executed = self.scan_and_trade(symbols)
                if executed:
                    log.info(f"Executed {len(executed)} signals this scan")

                log.info(f"Next scan in {self.scan_interval}s | Total signals: {self._signal_count}")
                time.sleep(self.scan_interval)

        except KeyboardInterrupt:
            log.info("Signal engine stopped by user.")

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "mode":          self.mode,
            "symbols":       len(self.symbols),
            "scan_count":    self._scan_count,
            "signal_count":  self._signal_count,
            "last_scan":     self._last_scan.strftime("%H:%M:%S") if self._last_scan else "Never",
            "risk_status":   self._risk.status(),
        }


# ── Helper: minimal signal object for RiskManager ────────────────────────────

class _make_signal:
    """Lightweight signal object compatible with RiskManager.approve()."""
    def __init__(self, symbol, action, price, quantity, score, mode):
        self.symbol   = symbol
        self.action   = action
        self.price    = price
        self.quantity = quantity
        self.strategy = f"ScoreEngine({score:+d})"
        self.mode     = mode
        self.meta     = {"score": score}
        self.exchange = "NSE"


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="F&O Signal Scanner")
    parser.add_argument("--mode",     default="PAPER", choices=["PAPER", "LIVE"])
    parser.add_argument("--symbols",  default="top50", choices=["top50", "all", "indices"])
    parser.add_argument("--interval", default=300, type=int, help="Scan interval in seconds")
    parser.add_argument("--once",     action="store_true", help="Scan once and exit")
    args = parser.parse_args()

    symbol_map = {
        "top50":   DEFAULT_SYMBOLS,
        "all":     ALL_FO_SYMBOLS,
        "indices": list(FO_INDICES.keys()),
    }

    engine = SignalEngine(
        mode          = args.mode,
        symbols       = symbol_map[args.symbols],
        scan_interval = args.interval,
    )

    if args.once:
        results = engine.scan_all()
        print(f"\n{'Symbol':<20} {'Score':>6} {'Action':>6} {'Price':>10}")
        print("-" * 50)
        for r in results:
            if r.get("error"):
                continue
            print(f"{r['symbol']:<20} {r['score']:>+6} {r['action']:>6} ₹{r['price']:>9,.2f}")
    else:
        engine.run_loop()
