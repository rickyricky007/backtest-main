from __future__ import annotations

import pandas as pd
from kiteconnect import KiteConnect
import streamlit as st


# ── Get Kite Instance ─────────────────────────────────────
def get_kite() -> KiteConnect:
    kite = st.session_state.get("kite")
    if not kite:
        raise Exception("Kite session not found. Please login again.")
    return kite


# ── Instrument Map (cached) ───────────────────────────────
@st.cache_data(ttl=86400)
def _load_instruments():
    try:
        kite = get_kite()
        instruments = kite.instruments("NSE")
        return {i["tradingsymbol"]: i["instrument_token"] for i in instruments}
    except Exception as e:
        raise Exception(f"Failed to load instruments: {e}")


def get_token(symbol: str):
    try:
        instrument_map = _load_instruments()
        token = instrument_map.get(symbol.upper())

        if not token:
            raise Exception(f"Instrument not found: {symbol}")

        return token
    except Exception as e:
        raise Exception(f"Token error: {e}")


# ── Holdings ──────────────────────────────────────────────
def fetch_holdings():
    try:
        kite = get_kite()
        return kite.holdings()
    except Exception as e:
        raise Exception(f"Holdings fetch failed: {e}")


def holdings_dataframe(rows):
    try:
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


# ── Positions ─────────────────────────────────────────────
def fetch_positions():
    try:
        kite = get_kite()
        return kite.positions()
    except Exception as e:
        raise Exception(f"Positions fetch failed: {e}")


def positions_dataframe(rows):
    try:
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


# ── Margins ───────────────────────────────────────────────
def fetch_margins():
    try:
        kite = get_kite()
        return kite.margins()
    except Exception as e:
        raise Exception(f"Margins fetch failed: {e}")


# ── Historical Data (SAFE) ────────────────────────────────
def fetch_historical_data(symbol: str, interval: str, days: int):
    from datetime import datetime, timedelta

    try:
        kite = get_kite()
        token = get_token(symbol)

        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)

        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=interval
        )

        if not data:
            return None

        df = pd.DataFrame(data)
        df.set_index("date", inplace=True)

        df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        }, inplace=True)

        return df

    except Exception as e:
        raise Exception(f"Historical data error ({symbol}): {e}")