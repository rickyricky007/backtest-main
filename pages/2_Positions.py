"""Positions — net vs intraday."""

from __future__ import annotations

import streamlit as st

import auth_streamlit as auth
import kite_data as kd

from dotenv import load_dotenv
import os
from alert_engine import send_telegram_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

st.set_page_config(page_title="Positions", layout="wide")

auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()


@st.cache_data(ttl=15, show_spinner="Loading…")
def _positions():
    return kd.fetch_positions()


with st.sidebar:
    st.subheader("Data")
    if st.button("Refresh now", type="primary", use_container_width=True, key="refresh_positions"):
        _positions.clear()
        st.rerun()
    st.caption("Cached up to ~15s.")
    auth.render_sidebar_kite_session(key_prefix="positions")
    auth.render_logout_controls(key="kite_logout_positions")

st.title("Positions")
st.caption("Net positions (carry) vs today’s day trades.")


try:
    data = _positions()
except Exception as e:
    auth.handle_kite_fetch_error(e, user_label="Could not load positions")

day = data.get("day") or []
net = data.get("net") or []

tab_day, tab_net = st.tabs(["Today (day)", "Net (overnight)"])

with tab_day:
    dfd = kd.positions_dataframe(day)
    if dfd.empty:
        st.info("No open day positions.")
    else:
        st.dataframe(dfd, use_container_width=True, hide_index=True, height=480)
        # P&L Alert
        if "pnl" in dfd.columns:
            total_pnl = dfd["pnl"].sum()
            if total_pnl <= -1000:  # 🔴 change this limit as you want
                send_telegram_message(TOKEN, CHAT_ID, 
                    f"🔴 <b>Loss Alert!</b>\nDay P&L: ₹{total_pnl:,.2f}")
            elif total_pnl >= 2000:  # 🟢 change this limit as you want
                send_telegram_message(TOKEN, CHAT_ID, 
                    f"🟢 <b>Profit Alert!</b>\nDay P&L: ₹{total_pnl:,.2f}")
with tab_net:
    dfn = kd.positions_dataframe(net)
    if dfn.empty:
        st.info("No net positions.")
    else:
        st.dataframe(dfn, use_container_width=True, hide_index=True, height=480)
