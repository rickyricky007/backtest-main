"""Historical Data — Breeze primary, Kite fallback. Equity + F&O."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import auth_streamlit as auth
import data_manager as dm

st.set_page_config(page_title="Historical Data", page_icon="📈", layout="wide")

auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()

st.title("📈 Historical Data")

# ── Data source badge ─────────────────────────────────────────────────────────
status = dm.status_report()
col_a, col_b = st.columns([3, 1])
with col_b:
    if status["breeze_available"]:
        st.success("📡 Breeze connected (primary)")
    elif status["kite_available"]:
        st.warning("📡 Kite fallback (Breeze offline)")
    else:
        st.error("❌ No data source available")

with col_a:
    st.caption("Breeze: free, 3 years, 1-sec data | Kite: fallback for equity")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Settings")
    auth.render_sidebar_kite_session(key_prefix="hist")
    auth.render_logout_controls(key="kite_logout_hist")

# ── Tabs: Equity | F&O ────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📊 Equity / Index", "📋 F&O Historical"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Equity / Index
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Equity & Index Historical Data")
    st.caption("Zerodha Kite fetch OHLCV candle data for any NSE symbol.")

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

    with col1:
        symbol = st.text_input(
            "Symbol", value="RELIANCE",
            placeholder="e.g. INFY, TCS, NIFTY 50",
            key="eq_symbol"
        ).strip().upper()

    with col2:
        interval = st.selectbox("Interval", [
            "minute", "3minute", "5minute", "10minute", "15minute",
            "30minute", "60minute", "day",
        ], index=6, key="eq_interval")

    with col3:
        exchange = st.selectbox("Exchange", ["NSE", "BSE"], key="eq_exchange")

    with col4:
        days = st.number_input("Days", min_value=1, max_value=1095, value=90, key="eq_days")

    fetch_btn = st.button("Fetch Data", type="primary", key="eq_fetch")

    if fetch_btn and symbol:
        with st.spinner(f"Fetching {symbol} from {'Breeze' if status['breeze_available'] else 'Kite'}..."):
            df = dm.get_historical(symbol, exchange=exchange, interval=interval, days=days)

        if df is None or df.empty:
            st.warning(
                f"No data for **{symbol}**. Check symbol name or try different interval/dates.\n\n"
                f"Data source tried: {'Breeze → Kite' if status['breeze_available'] else 'Kite'}"
            )
        else:
            source = dm.data_source()
            st.success(f"✅ {len(df)} candles loaded for **{symbol}** ({interval}) via **{source.upper()}**")

            # Chart
            st.subheader("Close Price")
            chart_df = df.set_index("datetime")[["close"]]
            st.line_chart(chart_df)

            # Stats
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Latest Close", f"₹{df['close'].iloc[-1]:,.2f}")
            c2.metric("Period High",  f"₹{df['high'].max():,.2f}")
            c3.metric("Period Low",   f"₹{df['low'].min():,.2f}")
            c4.metric("Avg Volume",   f"{int(df['volume'].mean()):,}")

            # Table
            st.subheader("OHLCV Table")
            display_df = df.copy()
            display_df["datetime"] = display_df["datetime"].astype(str)
            st.dataframe(
                display_df.sort_values("datetime", ascending=False),
                width="stretch", height=400
            )

            # Download
            st.download_button(
                label="⬇️ Download CSV",
                data=df.to_csv(index=False),
                file_name=f"{symbol}_{interval}_{days}d_{source}.csv",
                mime="text/csv",
            )

    elif fetch_btn and not symbol:
        st.warning("Please enter a symbol.")
    else:
        st.info("Enter a symbol above and click **Fetch Data** to load historical candles.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — F&O Historical (Breeze only)
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("F&O Historical Data")
    st.caption("3 years of Futures & Options historical data — powered by Breeze (free).")

    if not status["breeze_available"]:
        st.error(
            "❌ Breeze session required for F&O historical data.\n\n"
            "**Setup steps:**\n"
            "1. SSH into VPS: `ssh vps`\n"
            "2. Run: `python breeze_data.py --login`\n"
            "3. Open the URL, login, copy the `apisession=` token\n"
            "4. Run: `python breeze_data.py --token YOUR_TOKEN`"
        )
        st.stop()

    # F&O form
    col1, col2 = st.columns(2)

    with col1:
        fo_symbol = st.text_input(
            "Symbol", value="NIFTY",
            placeholder="NIFTY, BANKNIFTY, RELIANCE",
            key="fo_symbol"
        ).strip().upper()

        fo_product = st.selectbox(
            "Product Type", ["futures", "options"], key="fo_product"
        )

        fo_interval = st.selectbox(
            "Interval", ["minute", "5minute", "15minute", "30minute", "60minute", "day"],
            index=2, key="fo_interval"
        )

        fo_days = st.number_input("Days", min_value=1, max_value=365, value=30, key="fo_days")

    with col2:
        # Expiry date — default to last Thursday of current month
        today         = datetime.now()
        # Find next/current monthly expiry (last Thursday)
        year, month   = today.year, today.month
        next_month    = month % 12 + 1
        next_year     = year if month < 12 else year + 1
        last_day      = (datetime(next_year, next_month, 1) - timedelta(days=1))
        thursdays     = [last_day - timedelta(days=(last_day.weekday() - 3) % 7)]
        default_expiry = thursdays[0].strftime("%Y-%m-%dT06:00:00.000Z")

        fo_expiry = st.text_input(
            "Expiry Date",
            value=default_expiry,
            placeholder="2024-01-25T06:00:00.000Z",
            key="fo_expiry",
            help="Format: YYYY-MM-DDT06:00:00.000Z"
        )

        fo_strike = None
        fo_option_type = None

        if fo_product == "options":
            fo_strike = st.number_input(
                "Strike Price", min_value=0, value=22000, step=50, key="fo_strike"
            )
            fo_option_type = st.selectbox(
                "Option Type", ["call", "put"], key="fo_option_type"
            )

    fo_fetch = st.button("Fetch F&O Data", type="primary", key="fo_fetch")

    if fo_fetch and fo_symbol:
        with st.spinner(f"Fetching {fo_symbol} {fo_product} from Breeze..."):
            df = dm.get_fo_historical(
                symbol=fo_symbol,
                expiry_date=fo_expiry,
                strike_price=fo_strike,
                option_type=fo_option_type,
                product_type=fo_product,
                interval=fo_interval,
                days=fo_days,
            )

        if df is None or df.empty:
            st.warning(
                f"No F&O data for **{fo_symbol}** {fo_product}. "
                f"Check symbol, expiry date, or strike price."
            )
        else:
            label = f"{fo_symbol} {fo_product.upper()}"
            if fo_option_type:
                label += f" {int(fo_strike)} {fo_option_type.upper()}"

            st.success(f"✅ {len(df)} candles loaded for **{label}** ({fo_interval}) via BREEZE")

            # Chart
            st.subheader("Close Price")
            chart_df = df.set_index("datetime")[["close"]]
            st.line_chart(chart_df)

            # Stats
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Latest Close", f"₹{df['close'].iloc[-1]:,.2f}")
            c2.metric("Period High",  f"₹{df['high'].max():,.2f}")
            c3.metric("Period Low",   f"₹{df['low'].min():,.2f}")
            c4.metric("Avg Volume",   f"{int(df['volume'].mean()):,}")

            # Table
            st.subheader("OHLCV Table")
            display_df = df.copy()
            display_df["datetime"] = display_df["datetime"].astype(str)
            st.dataframe(
                display_df.sort_values("datetime", ascending=False),
                width="stretch", height=400
            )

            # Download
            fname = f"{fo_symbol}_{fo_product}_{fo_interval}_{fo_days}d_breeze.csv"
            st.download_button(
                label="⬇️ Download CSV",
                data=df.to_csv(index=False),
                file_name=fname,
                mime="text/csv",
            )

    elif fo_fetch and not fo_symbol:
        st.warning("Please enter a symbol.")
    else:
        st.info("Fill the form above and click **Fetch F&O Data**.")
