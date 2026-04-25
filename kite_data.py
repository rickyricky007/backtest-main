"""Shared Zerodha Kite + market data helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

# ── Token file paths ──────────────────────────────────────────────────────────
_TOKEN_FILE  = Path(__file__).resolve().parent / ".kite_access_token"
_TICKER_FILE = Path(__file__).resolve().parent / "ticker_data.json"

_TICKER_STALE_AFTER = 10  # seconds — mark feed stale if no update in 10s
_force_ignore_env_access_token = False


# ── Live ticker (KiteTicker WebSocket feed) ───────────────────────────────────
def read_ticker_data() -> dict[str, dict]:
    """
    Read live prices written by ticker_service.py.
    Returns empty dict if the file doesn't exist or data is stale (>10s old).
    """
    if not _TICKER_FILE.is_file():
        return {}
    try:
        data = json.loads(_TICKER_FILE.read_text(encoding="utf-8"))
        now  = time.time()
        ages = [now - v.get("updated_at", 0) for v in data.values() if isinstance(v, dict)]
        if ages and min(ages) < _TICKER_STALE_AFTER:
            return data
    except Exception:
        pass
    return {}


# ── Auth helpers ──────────────────────────────────────────────────────────────
def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing environment variable: {name}")
    return v


def load_access_token() -> str | None:
    load_dotenv(override=True)
    if _TOKEN_FILE.is_file():
        raw = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    if _force_ignore_env_access_token:
        return None
    from_env = os.getenv("ACCESS_TOKEN")
    if from_env and from_env.strip():
        return from_env.strip()
    return None


def set_ignore_env_access_token(ignore: bool) -> None:
    global _force_ignore_env_access_token
    _force_ignore_env_access_token = ignore


def save_access_token(token: str) -> None:
    set_ignore_env_access_token(False)
    _TOKEN_FILE.write_text(token.strip(), encoding="utf-8")


def clear_saved_access_token() -> None:
    if _TOKEN_FILE.is_file():
        _TOKEN_FILE.unlink()


def invalidate_session_after_auth_error() -> None:
    clear_saved_access_token()
    set_ignore_env_access_token(True)


def is_kite_auth_error(exc: BaseException) -> bool:
    if isinstance(exc, TokenException):
        return True
    s = str(exc).lower()
    return "incorrect api_key or access_token" in s


# ── Kite client ───────────────────────────────────────────────────────────────
def kite_login_url() -> str:
    load_dotenv(override=True)
    api_key = _require_env("API_KEY")
    return KiteConnect(api_key=api_key).login_url()


def exchange_request_token(request_token: str) -> str:
    load_dotenv(override=True)
    api_key    = _require_env("API_KEY")
    api_secret = _require_env("API_SECRET")
    kite       = KiteConnect(api_key=api_key)
    data       = kite.generate_session(request_token.strip(), api_secret=api_secret)
    access     = data["access_token"]
    save_access_token(access)
    return access


def kite_client() -> KiteConnect:
    load_dotenv(override=True)
    api_key = _require_env("API_KEY")
    access  = load_access_token()
    if not access:
        raise RuntimeError(
            "No Kite session yet. Run `python generate_token.py` in terminal, "
            "or set ACCESS_TOKEN in .env."
        )
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access)
    return kite


# ── Account data ──────────────────────────────────────────────────────────────
def fetch_margins() -> dict[str, Any]:
    return kite_client().margins()


def fetch_holdings() -> list[dict[str, Any]]:
    return kite_client().holdings()


def fetch_positions() -> dict[str, list[dict[str, Any]]]:
    return kite_client().positions()


# ── Index prices (yfinance fallback) ──────────────────────────────────────────
def nifty_spot() -> float | None:
    try:
        t    = yf.Ticker("^NSEI")
        info = t.info or {}
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        if price is not None:
            return float(price)
        hist = t.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def index_spot(ticker: str) -> dict[str, float | None]:
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            return {"price": None, "change": None, "pct": None}
        price = float(hist["Close"].iloc[-1])
        prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        change = price - prev
        pct    = (change / prev) * 100 if prev else 0
        return {"price": price, "change": change, "pct": pct}
    except Exception:
        return {"price": None, "change": None, "pct": None}


# ── DataFrames ────────────────────────────────────────────────────────────────
def holdings_dataframe(holdings: list[dict[str, Any]]) -> pd.DataFrame:
    if not holdings:
        return pd.DataFrame()
    df = pd.DataFrame(holdings)
    preferred = ["tradingsymbol", "quantity", "average_price", "last_price", "pnl", "day_change", "day_change_percentage"]
    cols  = [c for c in preferred if c in df.columns]
    extra = [c for c in df.columns if c not in cols]
    return df[cols + extra]


def positions_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    preferred = ["tradingsymbol", "product", "quantity", "average_price", "last_price", "pnl", "day_change"]
    cols  = [c for c in preferred if c in df.columns]
    extra = [c for c in df.columns if c not in cols]
    return df[cols + extra]


def fetch_historical(symbol: str, exchange: str, interval: str, from_date: str, to_date: str) -> pd.DataFrame:
    """Fetch historical OHLCV data from Kite."""
    kite             = kite_client()
    instruments      = kite.ltp(f"{exchange}:{symbol}")
    instrument_token = instruments[f"{exchange}:{symbol}"]["instrument_token"]
    data             = kite.historical_data(instrument_token, from_date, to_date, interval)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df
