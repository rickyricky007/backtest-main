"""Holdings — full table and export."""

from __future__ import annotations

import streamlit as st

import auth_streamlit as auth
import kite_data as kd

st.set_page_config(page_title="Holdings", layout="wide")

auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()


@st.cache_data(ttl=15, show_spinner="Loading…")
def _holdings():
    return kd.fetch_holdings()


with st.sidebar:
    st.subheader("Data")
    if st.button("Refresh now", type="primary", use_container_width=True, key="refresh_holdings"):
        _holdings.clear()
        st.rerun()
    st.caption("Cached up to ~15s.")
    auth.render_sidebar_kite_session(key_prefix="holdings")
    auth.render_logout_controls(key="kite_logout_holdings")

st.title("Holdings")
st.caption("Long-term portfolio from Kite holdings API.")


try:
    rows = _holdings()
except Exception as e:
    auth.handle_kite_fetch_error(e, user_label="Could not load holdings")

df = kd.holdings_dataframe(rows)

if df.empty:
    st.info("No holdings returned for this account.")
else:
    st.dataframe(df, use_container_width=True, hide_index=True, height=520)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name="holdings.csv",
        mime="text/csv",
    )
