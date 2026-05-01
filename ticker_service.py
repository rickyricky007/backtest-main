"""
Live Ticker Service — Zerodha KiteTicker WebSocket
====================================================
Subscribes to ALL 56 trading symbols (6 F&O indices + TOP_50_LIQUID stocks)
and writes live prices to ticker_data.json on every tick.

Uses an instruments cache (`instruments_cache.json`) to avoid the slow
~6,000-row Kite instruments() download on every restart. Cache refreshes
once per day.

Run ONCE after generating your token each morning (or via systemd):
    python ticker_service.py

Reads:
    - .kite_access_token  (Kite session)
    - fo_symbols.py       (TOP_50_LIQUID + FO_INDICES)

Writes:
    - ticker_data.json    (live prices, read by Streamlit + signal_engine)
    - instruments_cache.json (1-day cache of NSE/BSE instrument tokens)
"""

from __future__ import annotations

import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from kiteconnect import KiteTicker

import kite_data as kd
from fo_symbols import FO_INDICES, TOP_50_LIQUID, get_exchange
from logger import get_logger

log = get_logger("ticker_service")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent
TICKER_FILE     = BASE_DIR / "ticker_data.json"
INSTR_CACHE     = BASE_DIR / "instruments_cache.json"

# ── Cache config ──────────────────────────────────────────────────────────────
CACHE_TTL_HOURS = 24   # refresh instrument tokens once per day

# ── Hardcoded index instrument tokens (these never change) ────────────────────
# Source: Zerodha official instrument tokens for indices
INDEX_TOKENS: dict[int, str] = {
    256265: "NIFTY 50",
    260105: "BANK NIFTY",
    257801: "FINNIFTY",
    288009: "MIDCAP NIFTY",
    265:    "SENSEX",
    274441: "BANKEX",
}

# ── Runtime state ─────────────────────────────────────────────────────────────
_token_to_name: dict[int, str] = {}     # populated at startup
_prices:        dict[str, dict] = {}    # name → {price, change, pct, ...}
_running        = True


# ── Instrument cache helpers ──────────────────────────────────────────────────

def _cache_is_fresh() -> bool:
    """True if cache file exists and is younger than CACHE_TTL_HOURS."""
    try:
        if not INSTR_CACHE.is_file():
            return False
        age_s = time.time() - INSTR_CACHE.stat().st_mtime
        return age_s < CACHE_TTL_HOURS * 3600
    except Exception:
        log.error("_cache_is_fresh failed", exc_info=True)
        return False


def _load_cache() -> dict[str, int]:
    """Load symbol→instrument_token map from cache file. Returns {} on failure."""
    try:
        if not INSTR_CACHE.is_file():
            return {}
        return json.loads(INSTR_CACHE.read_text(encoding="utf-8"))
    except Exception:
        log.error("Failed to load instruments cache — will refresh", exc_info=True)
        return {}


def _save_cache(symbol_tokens: dict[str, int]) -> None:
    """Persist symbol→token map to cache file."""
    try:
        INSTR_CACHE.write_text(json.dumps(symbol_tokens, indent=2), encoding="utf-8")
        log.info(f"Saved instruments cache ({len(symbol_tokens)} symbols)")
    except Exception:
        log.error("Failed to save instruments cache", exc_info=True)


def _refresh_cache(kite) -> dict[str, int]:
    """
    Download NSE + BSE instruments from Kite, build symbol→token map for our universe.
    Returns dict; also writes to disk.
    """
    try:
        log.info("Refreshing instruments cache from Kite (this takes 2-3 seconds)...")
        symbol_tokens: dict[str, int] = {}

        # NSE — for TOP_50_LIQUID stocks
        nse_instruments = kite.instruments("NSE")
        nse_map = {i["tradingsymbol"]: i["instrument_token"] for i in nse_instruments}
        for sym in TOP_50_LIQUID:
            tok = nse_map.get(sym)
            if tok:
                symbol_tokens[sym] = tok
            else:
                log.warning(f"NSE token not found for {sym} — will skip subscription")

        log.info(f"Loaded {len(symbol_tokens)} NSE stock tokens")
        _save_cache(symbol_tokens)
        return symbol_tokens

    except Exception:
        log.error("Failed to refresh instruments cache", exc_info=True)
        return {}


def _build_subscription_map() -> dict[int, str]:
    """
    Returns {instrument_token: display_name} for all symbols we want to subscribe to.
    Combines hardcoded INDEX_TOKENS with stock tokens from cache (refreshed if stale).
    """
    try:
        token_to_name = dict(INDEX_TOKENS)   # start with indices

        if _cache_is_fresh():
            log.info("Using fresh instruments cache")
            stock_tokens = _load_cache()
        else:
            log.info("Instruments cache stale or missing — refreshing")
            kite = kd.kite_client()
            stock_tokens = _refresh_cache(kite)

        for sym, tok in stock_tokens.items():
            token_to_name[int(tok)] = sym

        log.info(f"Total subscription size: {len(token_to_name)} symbols "
                 f"({len(INDEX_TOKENS)} indices + {len(stock_tokens)} stocks)")
        return token_to_name

    except Exception:
        log.error("_build_subscription_map failed — falling back to indices only", exc_info=True)
        return dict(INDEX_TOKENS)


# ── Output writer ─────────────────────────────────────────────────────────────

def _write(data: dict) -> None:
    """Atomically write ticker_data.json."""
    try:
        tmp = TICKER_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        tmp.replace(TICKER_FILE)
    except Exception:
        log.error("Failed to write ticker_data.json", exc_info=True)


def _mark_offline() -> None:
    """Write an offline marker so Streamlit knows the feed stopped."""
    try:
        payload = {name: {**v, "live": False} for name, v in _prices.items()}
        _write(payload)
        log.info("Marked ticker feed offline")
    except Exception:
        log.error("_mark_offline failed", exc_info=True)


# ── KiteTicker callbacks ──────────────────────────────────────────────────────

def on_ticks(ws, ticks):
    try:
        for tick in ticks:
            token = tick.get("instrument_token")
            name  = _token_to_name.get(token)
            if not name:
                continue

            ohlc       = tick.get("ohlc") or {}
            prev_close = ohlc.get("close") or 0
            ltp        = tick.get("last_price") or 0
            change     = ltp - prev_close if prev_close else 0
            pct        = (change / prev_close * 100) if prev_close else 0

            _prices[name] = {
                "price":      ltp,
                "change":     round(change, 2),
                "pct":        round(pct, 2),
                "open":       ohlc.get("open"),
                "high":       ohlc.get("high"),
                "low":        ohlc.get("low"),
                "prev_close": prev_close,
                "volume":     tick.get("volume_traded"),
                "updated_at": time.time(),
                "live":       True,
            }

        if _prices:
            _write(_prices)

    except Exception:
        log.error("on_ticks error", exc_info=True)


def on_connect(ws, response):
    try:
        tokens = list(_token_to_name.keys())
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)
        log.info(f"✅ Connected — subscribed to {len(tokens)} symbols")
    except Exception:
        log.error("on_connect failed", exc_info=True)


def on_reconnect(ws, attempts_count):
    log.warning(f"🔄 Reconnecting... attempt {attempts_count}")


def on_noreconnect(ws):
    log.error("❌ Max reconnects reached — manual restart required")
    _mark_offline()


def on_error(ws, code, reason):
    log.warning(f"⚠️  WebSocket error {code}: {reason}")


def on_close(ws, code, reason):
    log.warning(f"🔴 Connection closed: {code} — {reason}")
    _mark_offline()


def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal received...")
    _mark_offline()
    _running = False
    sys.exit(0)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global _token_to_name

    try:
        signal.signal(signal.SIGINT,  _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        log.info("Loading Kite session...")
        try:
            kite = kd.kite_client()
        except RuntimeError as e:
            log.critical(f"Kite session not available: {e}")
            sys.exit(1)

        # Build subscription list (cache-aware)
        _token_to_name = _build_subscription_map()
        if not _token_to_name:
            log.critical("No symbols to subscribe to — aborting")
            sys.exit(1)

        # Connect WebSocket
        kws = KiteTicker(kite.api_key, kite.access_token)
        kws.on_ticks       = on_ticks
        kws.on_connect     = on_connect
        kws.on_reconnect   = on_reconnect
        kws.on_noreconnect = on_noreconnect
        kws.on_error       = on_error
        kws.on_close       = on_close

        log.info("Connecting to Kite WebSocket...")
        kws.connect(threaded=False)   # blocks until closed

    except Exception:
        log.error("ticker_service main loop crashed", exc_info=True)
        _mark_offline()
        raise


if __name__ == "__main__":
    main()
