"""
Breeze (ICICI Direct) Data Module
===================================
Primary data source for historical OHLC and F&O data.
Kite is used only for trading (orders, positions, account).

Usage:
    from breeze_data import breeze_client, get_historical, get_fo_historical

Daily session (run once after 8am):
    python breeze_data.py --login

IMPORTANT: Must be run from VPS (IP 13.206.86.130) — Breeze enforces IP whitelist.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── Session file (stores today's session token) ───────────────────────────────
_SESSION_FILE = Path(__file__).resolve().parent / ".breeze_session"


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}. Add to .env file.")
    return v


# ── Session management ────────────────────────────────────────────────────────

def save_session_token(token: str) -> None:
    """Save Breeze session token to file."""
    _SESSION_FILE.write_text(token.strip(), encoding="utf-8")
    _SESSION_FILE.chmod(0o600)
    print(f"[breeze] Session token saved to {_SESSION_FILE}")


def load_session_token() -> str | None:
    """Load saved session token."""
    if _SESSION_FILE.is_file():
        return _SESSION_FILE.read_text(encoding="utf-8").strip() or None
    return None


def breeze_client():
    """
    Return an authenticated BreezeConnect client.
    Raises RuntimeError if no session token found.
    """
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        raise RuntimeError(
            "breeze-connect not installed. Run: pip install breeze-connect"
        )

    api_key    = _require_env("BREEZE_API_KEY")
    api_secret = _require_env("BREEZE_API_SECRET")
    token      = load_session_token()

    if not token:
        raise RuntimeError(
            "No Breeze session. Generate one:\n"
            "  1. Go to https://api.icicidirect.com → View Apps → Login\n"
            "  2. Copy apisession= value from redirect URL\n"
            "  3. Run: python breeze_data.py --token YOUR_TOKEN"
        )

    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=token)
    return breeze


# ── Historical OHLC data ──────────────────────────────────────────────────────

def get_historical(
    symbol: str,
    exchange: str = "NSE",
    interval: str = "5minute",
    days: int = 30,
) -> pd.DataFrame:
    """
    Fetch historical OHLC data from Breeze.

    Args:
        symbol:   NSE symbol e.g. "NIFTY", "RELIANCE", "BANKNIFTY"
        exchange: "NSE" or "BSE"
        interval: "1second", "1minute", "5minute", "30minute", "1day"
        days:     Number of days of history to fetch

    Returns:
        DataFrame with columns: datetime, open, high, low, close, volume
    """
    breeze   = breeze_client()
    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    resp = breeze.get_historical_data_v2(
        interval=interval,
        from_date=start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        to_date=end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        stock_code=symbol,
        exchange_code=exchange,
        product_type="cash",
    )

    if resp.get("Status") != 200:
        raise RuntimeError(f"Breeze error: {resp.get('Error', resp)}")

    df = pd.DataFrame(resp["Success"])
    if df.empty:
        return df

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.rename(columns={
        "open":   "open",
        "high":   "high",
        "low":    "low",
        "close":  "close",
        "volume": "volume",
    })
    df = df.sort_values("datetime").reset_index(drop=True)
    return df[["datetime", "open", "high", "low", "close", "volume"]]


# ── F&O Historical data ───────────────────────────────────────────────────────

def get_fo_historical(
    symbol: str,
    expiry_date: str,
    strike_price: float | None = None,
    option_type: str | None = None,
    product_type: str = "futures",
    interval: str = "5minute",
    days: int = 30,
) -> pd.DataFrame:
    """
    Fetch F&O historical data from Breeze.

    Args:
        symbol:       e.g. "NIFTY", "BANKNIFTY", "RELIANCE"
        expiry_date:  "2024-01-25T06:00:00.000Z" format
        strike_price: e.g. 22000 (for options only)
        option_type:  "call" or "put" (for options only)
        product_type: "futures" or "options"
        interval:     "1minute", "5minute", "30minute", "1day"
        days:         Number of days of history

    Returns:
        DataFrame with OHLC data
    """
    breeze   = breeze_client()
    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    params = dict(
        interval=interval,
        from_date=start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        to_date=end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        stock_code=symbol,
        exchange_code="NFO",
        product_type=product_type,
        expiry_date=expiry_date,
    )
    if strike_price:
        params["strike_price"] = str(int(strike_price))
    if option_type:
        params["right"] = option_type  # "call" or "put"

    resp = breeze.get_historical_data_v2(**params)

    if resp.get("Status") != 200:
        raise RuntimeError(f"Breeze F&O error: {resp.get('Error', resp)}")

    df = pd.DataFrame(resp["Success"])
    if df.empty:
        return df

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    return df[["datetime", "open", "high", "low", "close", "volume"]]


# ── Live quotes ───────────────────────────────────────────────────────────────

def get_quote(symbol: str, exchange: str = "NSE") -> dict:
    """Get current live quote for a symbol."""
    breeze = breeze_client()
    resp = breeze.get_quotes(
        stock_code=symbol,
        exchange_code=exchange,
        product_type="cash",
        expiry_date="",
        right="",
        strike_price="",
    )
    if resp.get("Status") != 200:
        raise RuntimeError(f"Breeze quote error: {resp.get('Error', resp)}")
    return resp.get("Success", [{}])[0]


# ── Connection test ───────────────────────────────────────────────────────────

def test_connection() -> bool:
    """Test Breeze connection. Returns True if working."""
    try:
        breeze = breeze_client()
        funds  = breeze.get_funds()
        if funds.get("Status") == 200:
            print("[breeze] ✅ Connected successfully")
            return True
        else:
            print(f"[breeze] ❌ Auth failed: {funds.get('Error')}")
            return False
    except Exception as e:
        print(f"[breeze] ❌ Error: {e}")
        return False


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--token" in sys.argv:
        idx   = sys.argv.index("--token")
        token = sys.argv[idx + 1]
        save_session_token(token)
        print("[breeze] Token saved. Testing connection...")
        test_connection()

    elif "--test" in sys.argv:
        test_connection()

    elif "--login" in sys.argv:
        api_key = _require_env("BREEZE_API_KEY")
        print(f"\nOpen this URL in your browser and login:")
        print(f"https://api.icicidirect.com/apiuser/login?api_key={api_key}")
        print(f"\nAfter login, copy the apisession= value from the URL and run:")
        print(f"python breeze_data.py --token YOUR_SESSION_TOKEN\n")

    else:
        print("Usage:")
        print("  python breeze_data.py --login          # Get login URL")
        print("  python breeze_data.py --token TOKEN    # Save session token")
        print("  python breeze_data.py --test           # Test connection")
