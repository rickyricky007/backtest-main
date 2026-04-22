"""RSI Strategy Scanner — Live signals for indices + F&O stocks."""

from __future__ import annotations

import streamlit as st
import pandas as pd

import auth_streamlit as auth
import kite_data as kd
from rsi_strategy import (
    run_rsi_scanner,
    run_rsi_bounce_scanner,
    TOP_50_FO_STOCKS,
    INDICES,
)

st.set_page_config(page_title="RSI Strategy", layout="wide")
auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()

st.title("📊 RSI Strategy Scanner")
st.caption("Scans NIFTY, BANKNIFTY, FINNIFTY, SENSEX + Top 50 F&O stocks every 15 mins.")

# ── Session state ──────────────────────────────────────────────────────────
if "rsi_signals" not in st.session_state:
    st.session_state["rsi_signals"] = []
if "rsi_paper_trades" not in st.session_state:
    st.session_state["rsi_paper_trades"] = []
if "rsi_alerted" not in st.session_state:
    st.session_state["rsi_alerted"] = set()
if "bounce_signals" not in st.session_state:
    st.session_state["bounce_signals"] = []
if "bounce_alerted" not in st.session_state:
    st.session_state["bounce_alerted"] = set()

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Scanner Settings")
    rsi_buy = st.number_input("RSI BUY threshold", 1, 50, 15)
    rsi_sell = st.number_input("RSI SELL threshold", 50, 99, 85)
    scan_interval = st.selectbox("Scan every", ["15 minutes", "5 minutes", "1 minute"])

    st.divider()
    if st.button("🔍 Scan Now", type="primary", use_container_width=True):
        st.session_state["run_scan"] = True
    if st.button("📈 Run Bounce Scan", type="secondary", use_container_width=True):
        st.session_state["run_bounce_scan"] = True
    if st.button("🗑️ Clear All", use_container_width=True):
        st.session_state["rsi_signals"] = []
        st.session_state["rsi_paper_trades"] = []
        st.session_state["rsi_alerted"] = set()
        st.session_state["bounce_signals"] = []
        st.session_state["bounce_alerted"] = set()
        st.rerun()

    auth.render_sidebar_kite_session(key_prefix="rsi")
    auth.render_logout_controls(key="kite_logout_rsi")

# ── Dashboard metrics ──────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Signals", len(st.session_state["rsi_signals"]))
col2.metric("Paper Trades", len(st.session_state["rsi_paper_trades"]))
buy_count = len([s for s in st.session_state["rsi_signals"] if s["signal"] == "BUY"])
col3.metric("BUY / SELL", f"{buy_count} / {len(st.session_state['rsi_signals']) - buy_count}")
col4.metric("Bounce Signals", len(st.session_state["bounce_signals"]))

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────
tab_signals, tab_trades, tab_bounce = st.tabs([
    "📡 Live Signals",
    "📋 Paper Trades",
    "🔄 RSI Bounce (20→30)",
])

with tab_signals:
    if st.session_state["rsi_signals"]:
        df = pd.DataFrame(st.session_state["rsi_signals"])
        # def highlight(row):
        #     color = "background-color: #d4edda" if row["signal"] == "BUY" else "background-color: #f8d7da"
        #     return [color] * len(row)
        # st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True, hide_index=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No signals yet. Click **Scan Now** to start.")

with tab_trades:
    if st.session_state["rsi_paper_trades"]:
        st.dataframe(
            pd.DataFrame(st.session_state["rsi_paper_trades"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No paper trades yet.")

with tab_bounce:
    st.subheader("RSI Bounce Strategy")
    st.caption("Detects when RSI crosses above 20 after being below 20. Target: RSI reaches 30.")

    col_a, col_b = st.columns(2)
    col_a.metric("Bounce Signals Found", len(st.session_state["bounce_signals"]))
    open_bounce = [s for s in st.session_state["bounce_signals"] if s["status"] == "OPEN"]
    col_b.metric("Open Trades", len(open_bounce))

    if st.session_state["bounce_signals"]:
        df_bounce = pd.DataFrame(st.session_state["bounce_signals"])
        st.dataframe(df_bounce, use_container_width=True, hide_index=True)
    else:
        st.info("No bounce signals yet. Click **Run Bounce Scan** in the sidebar.")

# ── Run RSI Scanner ────────────────────────────────────────────────────────
if st.session_state.get("run_scan"):
    st.session_state["run_scan"] = False
    with st.spinner("🔍 Scanning all symbols..."):
        try:
            kite = st.session_state.get("kite")
            new_signals = run_rsi_scanner(
                kite,
                {},
                st.session_state["rsi_paper_trades"],
                st.session_state["rsi_alerted"],
            )
            st.session_state["rsi_signals"].extend(new_signals)
            if new_signals:
                st.success(f"✅ Found {len(new_signals)} new signals!")
            else:
                st.info("No new signals found. RSI is neutral for all symbols.")
            st.rerun()
        except Exception as e:
            st.error(f"Scan error: {e}")

# ── Run Bounce Scanner ─────────────────────────────────────────────────────
if st.session_state.get("run_bounce_scan"):
    st.session_state["run_bounce_scan"] = False
    with st.spinner("🔄 Scanning for RSI bounce setups..."):
        try:
            new_bounces = run_rsi_bounce_scanner(
                st.session_state["bounce_alerted"],
            )
            st.session_state["bounce_signals"].extend(new_bounces)
            if new_bounces:
                st.success(f"✅ Found {len(new_bounces)} bounce signals!")
            else:
                st.info("No bounce setups found right now.")
            st.rerun()
        except Exception as e:
            st.error(f"Bounce scan error: {e}")