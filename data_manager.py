"""
Data Manager — Unified Data Layer
===================================
Single entry point for all historical and live market data.

Priority:
    1. Breeze (ICICI) — primary: free, 3 years, 1-second data, F&O historical
    2. Kite  (Zerodha) — fallback: for equity historical when Breeze unavailable
    3. yfinance        — last resort: for signal engine (15-min delay, US + India)

Usage:
    from data_manager import get_historical, get_fo_historical, data_source

    df = get_historical("RELIANCE", interval="5minute", days=30)
    df = get_fo_historical("NIFTY", expiry="2024-01-25T06:00:00.000Z", days=10)
    print(data_source())   # "breeze" or "kite"

Notes:
    - Breeze must be running from VPS (IP enforced by ICICI)
    - Kite fallback requires valid access token
    - All functions return pd.DataFrame with columns: datetime, open, high, low, close, volume
    - Returns empty DataFrame on failure — never raises, always logs
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from logger import get_logger

load_dotenv()
log = get_logger("data_manager")

# ── Interval mapping (Breeze ↔ Kite formats) ──────────────────────────────────
_BREEZE_INTERVAL = {
    "minute":    "1minute",
    "3minute":   "3minute",
    "5minute":   "5minute",
    "10minute":  "10minute",
    "15minute":  "15minute",
    "30minute":  "30minute",
    "60minute":  "1hour",
    "day":       "1day",
    "week":      "1day",   # Breeze doesn't have weekly — use daily
}

_KITE_INTERVAL = {
    "1minute":  "minute",
    "3minute":  "3minute",
    "5minute":  "5minute",
    "10minute": "10minute",
    "15minute": "15minute",
    "30minute": "30minute",
    "1hour":    "60minute",
    "1day":     "day",
}

# Track which source was used last
_last_source: str = "none"


def data_source() -> str:
    """Returns which data source was used last: 'breeze', 'kite', or 'yfinance'."""
    return _last_source


def _is_breeze_available() -> bool:
    """Check if Breeze session file exists and keys are configured."""
    session_file = Path(__file__).parent / ".breeze_session"
    has_key      = bool(os.getenv("BREEZE_API_KEY"))
    has_session  = session_file.is_file() and bool(session_file.read_text().strip())
    return has_key and has_session


def _is_kite_available() -> bool:
    """Check if Kite access token exists."""
    token_file = Path(__file__).parent / ".kite_access_token"
    return token_file.is_file() and bool(token_file.read_text().strip())


# ── Breeze fetch ───────────────────────────────────────────────────────────────

def _fetch_breeze(
    symbol: str,
    exchange: str,
    interval: str,
    days: int,
) -> pd.DataFrame:
    """Fetch historical data from Breeze. Returns empty DataFrame on failure."""
    global _last_source
    try:
        import breeze_data as bd
        breeze_interval = _BREEZE_INTERVAL.get(interval, interval)
        df = bd.get_historical(
            symbol=symbol,
            exchange=exchange,
            interval=breeze_interval,
            days=days,
        )
        if not df.empty:
            _last_source = "breeze"
            log.info(f"[breeze] {symbol} {interval} {days}d — {len(df)} candles")
        return df
    except Exception as e:
        log.warning(f"[breeze] Failed for {symbol}: {e}")
        return pd.DataFrame()


# ── Kite fetch ────────────────────────────────────────────────────────────────

def _fetch_kite(
    symbol: str,
    exchange: str,
    interval: str,
    days: int,
) -> pd.DataFrame:
    """Fetch historical data from Kite. Returns empty DataFrame on failure."""
    global _last_source
    try:
        import kite_data as kd
        kite = kd.kite_client()

        # Get instrument token
        instruments = kite.instruments(exchange)
        token_map   = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}
        token       = token_map.get(symbol.upper())
        if not token:
            log.warning(f"[kite] Symbol not found: {symbol}")
            return pd.DataFrame()

        to_date   = datetime.now()
        from_date = to_date - timedelta(days=days)

        # Kite interval format
        kite_interval = _KITE_INTERVAL.get(interval, interval)

        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=kite_interval,
        )
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df = df.rename(columns={"date": "datetime"})
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df[["datetime", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("datetime").reset_index(drop=True)

        _last_source = "kite"
        log.info(f"[kite] {symbol} {interval} {days}d — {len(df)} candles")
        return df

    except Exception as e:
        log.warning(f"[kite] Failed for {symbol}: {e}")
        return pd.DataFrame()


# ── Public API ────────────────────────────────────────────────────────────────

def get_historical(
    symbol:   str,
    exchange: str = "NSE",
    interval: str = "5minute",
    days:     int = 30,
) -> pd.DataFrame:
    """
    Fetch historical OHLCV data.

    Tries Breeze first, falls back to Kite, then returns empty DataFrame.

    Args:
        symbol:   NSE symbol e.g. "RELIANCE", "NIFTY 50", "BANKNIFTY"
        exchange: "NSE" or "BSE"
        interval: "minute", "5minute", "15minute", "30minute", "60minute", "day"
        days:     Number of days of history (Breeze: up to 1095, Kite: up to 2000)

    Returns:
        DataFrame with columns: datetime, open, high, low, close, volume
        Empty DataFrame if both sources fail.
    """
    # Try Breeze first
    if _is_breeze_available():
        df = _fetch_breeze(symbol, exchange, interval, days)
        if not df.empty:
            return df
        log.info(f"Breeze failed for {symbol} — trying Kite fallback")

    # Fall back to Kite
    if _is_kite_available():
        df = _fetch_kite(symbol, exchange, interval, days)
        if not df.empty:
            return df
        log.warning(f"Kite also failed for {symbol}")

    log.error(f"No data available for {symbol} — both Breeze and Kite failed")
    return pd.DataFrame()


def get_fo_historical(
    symbol:       str,
    expiry_date:  str,
    strike_price: float | None = None,
    option_type:  str | None   = None,
    product_type: str          = "futures",
    interval:     str          = "5minute",
    days:         int          = 30,
) -> pd.DataFrame:
    """
    Fetch F&O historical data (Breeze only — Kite doesn't provide free F&O historical).

    Args:
        symbol:       e.g. "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry_date:  "2024-01-25T06:00:00.000Z" format
        strike_price: e.g. 22000 (options only)
        option_type:  "call" or "put" (options only)
        product_type: "futures" or "options"
        interval:     "1minute", "5minute", "30minute", "1day"
        days:         Days of history

    Returns:
        DataFrame with OHLCV data. Empty DataFrame if Breeze unavailable.
    """
    global _last_source

    if not _is_breeze_available():
        log.warning("F&O historical data requires Breeze — session not available")
        return pd.DataFrame()

    try:
        import breeze_data as bd
        breeze_interval = _BREEZE_INTERVAL.get(interval, interval)
        df = bd.get_fo_historical(
            symbol=symbol,
            expiry_date=expiry_date,
            strike_price=strike_price,
            option_type=option_type,
            product_type=product_type,
            interval=breeze_interval,
            days=days,
        )
        if not df.empty:
            _last_source = "breeze"
            log.info(f"[breeze F&O] {symbol} {product_type} — {len(df)} candles")
        return df

    except Exception as e:
        log.error(f"[breeze F&O] Failed for {symbol}: {e}")
        return pd.DataFrame()


def get_ohlcv_for_signal(
    symbol: str,
    interval: str = "15m",
    days: int = 5,
) -> dict | None:
    """
    Fetch OHLCV formatted for signal_engine.
    Tries Breeze → Kite → yfinance (15-min delay fallback).

    Returns dict with keys: closes, highs, lows, volumes
    Returns None if all sources fail.
    """
    global _last_source

    # Try Breeze first
    if _is_breeze_available():
        breeze_interval = "15minute" if interval == "15m" else "5minute"
        df = _fetch_breeze(symbol, "NSE", breeze_interval, days)
        if not df.empty and len(df) >= 30:
            return {
                "closes":  df["close"].tolist(),
                "highs":   df["high"].tolist(),
                "lows":    df["low"].tolist(),
                "volumes": df["volume"].tolist(),
            }

    # Try Kite
    if _is_kite_available():
        kite_interval = "15minute" if interval == "15m" else "5minute"
        df = _fetch_kite(symbol, "NSE", kite_interval, days)
        if not df.empty and len(df) >= 30:
            return {
                "closes":  df["close"].tolist(),
                "highs":   df["high"].tolist(),
                "lows":    df["low"].tolist(),
                "volumes": df["volume"].tolist(),
            }

    # Last resort — yfinance (15-min delayed)
    try:
        import yfinance as yf
        from fo_symbols import get_yf_ticker
        ticker = get_yf_ticker(symbol)
        df = yf.Ticker(ticker).history(period=f"{days}d", interval=interval)

        if df.empty or len(df) < 30:
            return None

        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)

        _last_source = "yfinance"
        return {
            "closes":  df["Close"].dropna().tolist(),
            "highs":   df["High"].dropna().tolist(),
            "lows":    df["Low"].dropna().tolist(),
            "volumes": df["Volume"].dropna().tolist(),
        }
    except Exception as e:
        log.warning(f"[yfinance] Failed for {symbol}: {e}")
        return None


def status_report() -> dict:
    """Returns current data source status for dashboard display."""
    return {
        "breeze_available": _is_breeze_available(),
        "kite_available":   _is_kite_available(),
        "last_source":      _last_source,
    }
