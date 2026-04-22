"""Funds & margins — raw Kite margin payload."""

from __future__ import annotations

import json

import streamlit as st

import auth_streamlit as auth
import kite_data as kd

from dotenv import load_dotenv
import os
from alert_engine import send_telegram_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

st.set_page_config(page_title="Funds", layout="wide")

auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()


@st.cache_data(ttl=15, show_spinner="Loading…")
def _margins():
    return kd.fetch_margins()


with st.sidebar:
    st.subheader("Data")
    if st.button("Refresh now", type="primary", use_container_width=True, key="refresh_funds"):
        _margins.clear()
        st.rerun()
    st.caption("Cached up to ~15s.")
    auth.render_sidebar_kite_session(key_prefix="funds")
    auth.render_logout_controls(key="kite_logout_funds")

st.title("Funds & margins")
st.caption("Full margins() response for debugging and detail.")


try:
    margins = _margins()
except Exception as e:
    auth.handle_kite_fetch_error(e, user_label="Could not load margins")

st.json(margins)

# Funds Alert
try:
    available_cash = margins["equity"]["available"]["live_balance"]
    if available_cash <= 10000:  # 🔴 change this limit as you want
        send_telegram_message(TOKEN, CHAT_ID,
            f"⚠️ <b>Low Funds Alert!</b>\nAvailable Cash: ₹{available_cash:,.2f}")
except Exception:
    pass

raw = json.dumps(margins, indent=2, default=str)
st.download_button(
    "Download JSON",
    data=raw.encode("utf-8"),
    file_name="margins.json",
    mime="application/json",
)
