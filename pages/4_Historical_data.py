"""Download Yahoo Finance history into local SQLite for backtesting."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf

import local_store as store

st.set_page_config(page_title="Historical data", layout="wide")

st.title("Historical data (Yahoo Finance)")
st.caption(
    f"Fetches OHLCV from Yahoo Finance and stores it in **{store.db_path().name}** for offline backtests."
)

with st.sidebar:
    st.subheader("SQLite")
    st.caption(str(store.db_path()))
    if st.button("Init / verify tables", key="hist_init_db"):
        store.init_db()
        st.success("Schema ready.")

col_a, col_b, col_c = st.columns(3)
with col_a:
    symbol = st.text_input("Symbol", value="^NSEI", help="Examples: ^NSEI, RELIANCE.NS, AAPL")
with col_b:
    interval = st.selectbox(
        "Interval",
        options=["1d", "1wk", "1mo", "1h", "90m", "60m", "30m", "15m", "5m", "1m"],
        index=0,
    )
with col_c:
    lookback = st.selectbox("Quick range", ["Custom", "1y", "2y", "5y", "max"], index=1)

today = date.today()
if lookback == "Custom":
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("Start", value=today - timedelta(days=365))
    with c2:
        end_d = st.date_input("End", value=today)
else:
    start_d = None
    end_d = today

if st.button("Fetch & save to SQLite", type="primary"):
    try:
        tkr = yf.Ticker(symbol.strip())
        if lookback == "Custom":
            df = tkr.history(
                start=start_d.isoformat(),
                end=(end_d + timedelta(days=1)).isoformat(),
                interval=interval,
                auto_adjust=False,
            )
        else:
            df = tkr.history(period=lookback, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            st.warning("No rows returned. Try another symbol, interval, or date range.")
        else:
            n = store.save_historical_bars(symbol.strip(), interval, df)
            st.success(f"Saved **{n}** bars for `{symbol.strip().upper()}` @ `{interval}`.")
            st.dataframe(df.tail(20), use_container_width=True)
    except Exception as e:
        st.error(str(e))

st.divider()
st.subheader("Series already in the database")
store.init_db()
meta = store.list_historical_series()
if meta.empty:
    st.info("No historical series stored yet.")
else:
    st.dataframe(meta, use_container_width=True, hide_index=True)

st.subheader("Load preview from database")
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    prev_sym = st.text_input("Preview symbol", value=symbol.strip().upper(), key="prev_sym")
with c2:
    prev_iv = st.text_input("Preview interval", value=interval, key="prev_iv")
with c3:
    prev_n = st.number_input("Max rows", min_value=50, max_value=50000, value=2000, step=50)

if st.button("Load from SQLite"):
    try:
        pdf = store.load_historical_bars(prev_sym, prev_iv, limit=int(prev_n))
        if pdf.empty:
            st.warning("No rows in DB for that symbol/interval.")
        else:
            st.dataframe(pdf, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(str(e))

with st.expander("Delete a series from SQLite"):
    if meta.empty:
        st.caption("Nothing to delete.")
    else:
        keys = [f"{r['symbol']} | {r['interval']}" for _, r in meta.iterrows()]
        pick = st.selectbox("Choose series", keys)
        if st.button("Delete selected series", type="primary"):
            sym, iv = pick.split(" | ", 1)
            n = store.delete_historical_series(sym, iv)
            st.success(f"Removed **{n}** rows.")
            st.rerun()
