"""Historical Data — fetch OHLCV from Kite and display chart + table."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import auth_streamlit as auth
import kite_data as kd

st.set_page_config(page_title="Historical Data", page_icon="📈", layout="wide")

auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()

st.title("📈 Historical Data")
st.caption("Fetch OHLCV candle data from Zerodha Kite for any NSE symbol.")

# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Settings")
    auth.render_sidebar_kite_session(key_prefix="hist")
    auth.render_logout_controls(key="kite_logout_hist")


# ── Instrument map (cached 24h) ───────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner="Loading instruments…")
def _load_instruments() -> dict[str, int]:
    kite = kd.kite_client()
    instruments = kite.instruments("NSE")
    return {i["tradingsymbol"]: i["instrument_token"] for i in instruments}


# ── Historical data fetch ─────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Fetching historical data…")
def _fetch(symbol: str, interval: str, days: int) -> pd.DataFrame | None:
    try:
        instrument_map = _load_instruments()
        token = instrument_map.get(symbol.upper())
        if not token:
            return None

        kite = kd.kite_client()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)

        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )
        if not data:
            return None

        df = pd.DataFrame(data)
        df.set_index("date", inplace=True)
        df.rename(columns={
            "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume"
        }, inplace=True)
        return df

    except Exception as e:
        auth.handle_kite_fetch_error(e, user_label="Historical data fetch failed")
        return None


# ── Input form ────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    symbol = st.text_input("Symbol", value="RELIANCE", placeholder="e.g. INFY, TCS, NIFTY 50").strip().upper()

with col2:
    interval = st.selectbox("Interval", [
        "minute", "3minute", "5minute", "10minute", "15minute",
        "30minute", "60minute", "day", "week", "month"
    ], index=7)

with col3:
    days = st.number_input("Days of data", min_value=1, max_value=2000, value=90)

fetch_btn = st.button("Fetch Data", type="primary", use_container_width=False)

# ── Display ───────────────────────────────────────────────────────────────────
if fetch_btn and symbol:
    df = _fetch(symbol, interval, days)

    if df is None or df.empty:
        st.warning(f"No data returned for **{symbol}**. Check the symbol name or try a different interval/date range.")
    else:
        st.success(f"✅ {len(df)} candles loaded for **{symbol}** ({interval})")

        # Chart
        st.subheader("Close Price")
        st.line_chart(df["Close"])

        # OHLCV stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latest Close", f"₹{df['Close'].iloc[-1]:,.2f}")
        c2.metric("Period High",  f"₹{df['High'].max():,.2f}")
        c3.metric("Period Low",   f"₹{df['Low'].min():,.2f}")
        c4.metric("Avg Volume",   f"{int(df['Volume'].mean()):,}")

        # Full table
        st.subheader("OHLCV Table")
        st.dataframe(df.sort_index(ascending=False), use_container_width=True, height=400)

        # Download
        csv = df.to_csv()
        st.download_button(
            label="⬇️ Download CSV",
            data=csv,
            file_name=f"{symbol}_{interval}_{days}d.csv",
            mime="text/csv",
        )
elif fetch_btn and not symbol:
    st.warning("Please enter a symbol.")
else:
    st.info("Enter a symbol above and click **Fetch Data** to load historical candles.")
