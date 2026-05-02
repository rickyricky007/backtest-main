"""Positions — net vs intraday."""

from __future__ import annotations

import streamlit as st
import os
from dotenv import load_dotenv

import auth_streamlit as auth
import kite_data as kd
from alert_engine import send_telegram_message


# ── Load ENV ─────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


st.set_page_config(page_title="Positions", layout="wide")

auth.render_auth_cleared_banner()

# Ensure Kite session
if not auth.ensure_kite_ready():
    st.stop()


# ── Session State for Alert Control ──────────────────────
if "last_alert" not in st.session_state:
    st.session_state.last_alert = None


# ── Cached Fetch ─────────────────────────────────────────
@st.cache_data(ttl=15, show_spinner="Loading positions…")
def _positions():
    return kd.fetch_positions()


# ── Sidebar ──────────────────────────────────────────────
with st.sidebar:
    st.subheader("Data")

    if st.button("Refresh now", type="primary", width="stretch"):
        _positions.clear()
        st.rerun()

    st.caption("Cached ~15 seconds")

    auth.render_sidebar_kite_session(key_prefix="positions")
    auth.render_logout_controls(key="kite_logout_positions")


# ── Main UI ──────────────────────────────────────────────
st.title("Positions")
st.caption("Net positions (carry) vs today’s trades")


# ── Fetch Data ───────────────────────────────────────────
try:
    data = _positions()
except Exception as e:
    auth.handle_kite_fetch_error(e, user_label="Failed to load positions")
    st.stop()


day = data.get("day") or []
net = data.get("net") or []


# ── Tabs ─────────────────────────────────────────────────
tab_day, tab_net = st.tabs(["Today (day)", "Net (overnight)"])


# ── Day Positions ────────────────────────────────────────
with tab_day:
    dfd = kd.positions_dataframe(day)

    if dfd.empty:
        st.info("No open day positions.")
    else:
        st.dataframe(dfd, width="stretch", hide_index=True, height=480)

        # 🔔 P&L Alert (only once per threshold)
        if "pnl" in dfd.columns:
            total_pnl = float(dfd["pnl"].sum())
            last = st.session_state.last_alert

            # Debug / visibility
            st.write(f"P&L: ₹{total_pnl:,.2f}")
            st.write(f"Last Alert: {last}")

            if TOKEN and CHAT_ID:

                # 🔴 Loss alert
                if total_pnl <= -1000 and last != "LOSS":
                    send_telegram_message(
                        TOKEN, CHAT_ID,
                        f"🔴 <b>Loss Alert!</b>\nDay P&L: ₹{total_pnl:,.2f}"
                    )
                    st.session_state.last_alert = "LOSS"

                # 🟢 Profit alert
                elif total_pnl >= 2000 and last != "PROFIT":
                    send_telegram_message(
                        TOKEN, CHAT_ID,
                        f"🟢 <b>Profit Alert!</b>\nDay P&L: ₹{total_pnl:,.2f}"
                    )
                    st.session_state.last_alert = "PROFIT"

                # 🔄 Reset when back to normal
                elif -1000 < total_pnl < 2000:
                    st.session_state.last_alert = None

        st.success("✅ Data refreshed")


# ── Net Positions ────────────────────────────────────────
with tab_net:
    dfn = kd.positions_dataframe(net)

    if dfn.empty:
        st.info("No net positions.")
    else:
        st.dataframe(dfn, width="stretch", hide_index=True, height=480)