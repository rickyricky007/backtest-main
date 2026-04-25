"""
Live Ticker Service — Zerodha KiteTicker WebSocket
====================================================
Subscribes to Nifty 50, Bank Nifty and Sensex and writes
live prices to ticker_data.json every tick.

Run ONCE after generating your token each morning:
    python ticker_service.py

Keep this running in a separate terminal alongside:
    streamlit run app.py
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

from kiteconnect import KiteTicker

import kite_data as kd

# ── Output file (read by Streamlit app) ──────────────────────────────────────
TICKER_FILE = Path(__file__).resolve().parent / "ticker_data.json"

# ── Instrument tokens (NSE indices + BSE Sensex) ─────────────────────────────
TOKENS = {
    256265: "NIFTY 50",
    260105: "BANK NIFTY",
    265:    "SENSEX",
}

# ── State ─────────────────────────────────────────────────────────────────────
_prices: dict[str, dict] = {}
_running = True


def _write(data: dict) -> None:
    try:
        TICKER_FILE.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception as e:
        print(f"[ticker] Write error: {e}")


def _mark_offline() -> None:
    """Write an offline marker so Streamlit knows the feed stopped."""
    payload = {name: {**v, "live": False} for name, v in _prices.items()}
    _write(payload)


def on_ticks(ws, ticks):
    for tick in ticks:
        token = tick.get("instrument_token")
        name = TOKENS.get(token)
        if not name:
            continue

        ohlc = tick.get("ohlc") or {}
        prev_close = ohlc.get("close") or 0
        ltp = tick.get("last_price") or 0
        change = ltp - prev_close if prev_close else 0
        pct = (change / prev_close * 100) if prev_close else 0

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
        names = " | ".join(
            f"{n}: ₹{v['price']:,.2f} ({'+' if v['pct'] >= 0 else ''}{v['pct']:.2f}%)"
            for n, v in _prices.items()
        )
        print(f"\r[LIVE] {names}   ", end="", flush=True)


def on_connect(ws, response):
    tokens = list(TOKENS.keys())
    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_FULL, tokens)
    print(f"[ticker] ✅ Connected — subscribed to: {', '.join(TOKENS.values())}")


def on_reconnect(ws, attempts_count):
    print(f"\n[ticker] 🔄 Reconnecting… (attempt {attempts_count})")


def on_noreconnect(ws):
    print("\n[ticker] ❌ Max reconnects reached. Restart this script.")
    _mark_offline()


def on_error(ws, code, reason):
    print(f"\n[ticker] ⚠️  Error {code}: {reason}")


def on_close(ws, code, reason):
    print(f"\n[ticker] 🔴 Connection closed: {code} — {reason}")
    _mark_offline()


def _handle_signal(sig, frame):
    global _running
    print("\n[ticker] Shutting down…")
    _mark_offline()
    _running = False
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("[ticker] Loading Kite session…")
    try:
        kite = kd.kite_client()
    except RuntimeError as e:
        print(f"[ticker] ❌ {e}")
        sys.exit(1)

    kws = KiteTicker(kite.api_key, kite.access_token)
    kws.on_ticks      = on_ticks
    kws.on_connect    = on_connect
    kws.on_reconnect  = on_reconnect
    kws.on_noreconnect = on_noreconnect
    kws.on_error      = on_error
    kws.on_close      = on_close

    print("[ticker] Connecting to Kite WebSocket…")
    kws.connect(threaded=False)  # blocks until closed


if __name__ == "__main__":
    main()
