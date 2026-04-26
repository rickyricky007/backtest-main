"""Holdings — full table and export."""

from __future__ import annotations

import streamlit as st

import auth_streamlit as auth
import kite_data as kd

st.set_page_config(page_title="Holdings", layout="wide")

auth.render_auth_cleared_banner()

# Ensure Kite session
if not auth.ensure_kite_ready():
    st.stop()


# ── Cached Fetch ─────────────────────────────────────────────
@st.cache_data(ttl=15, show_spinner="Loading holdings…")
def _holdings():
    return kd.fetch_holdings()


# ── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Data")

    if st.button("Refresh now", type="primary", use_container_width=True):
        _holdings.clear()
        st.rerun()

    st.caption("Cached ~15 seconds")

    auth.render_sidebar_kite_session(key_prefix="holdings")
    auth.render_logout_controls(key="kite_logout_holdings")


# ── Main UI ──────────────────────────────────────────────────
st.title("Holdings")
st.caption("Long-term portfolio from Kite Holdings API")


# ── Fetch Data ───────────────────────────────────────────────
try:
    rows = _holdings()
except Exception as e:
    auth.handle_kite_fetch_error(e, user_label="Failed to load holdings")
    st.stop()


# ── Convert to DataFrame ─────────────────────────────────────
df = kd.holdings_dataframe(rows)


# ── Display ──────────────────────────────────────────────────
if df.empty:
    st.info("No holdings found in your account.")
else:
    st.dataframe(df, use_container_width=True, hide_index=True, height=520)

    st.download_button(
        label="Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="holdings.csv",
        mime="text/csv",
    )