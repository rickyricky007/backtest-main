"""Trading dashboard — main overview (run with: streamlit run app.py)."""

from __future__ import annotations

import time
import streamlit as st

import auth_streamlit as auth
import kite_data as kd

st.set_page_config(
    page_title="Trading dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

auth.render_auth_cleared_banner()


@st.cache_data(ttl=15, show_spinner="Loading account…")
def _margins():
    return kd.fetch_margins()


@st.cache_data(ttl=15, show_spinner="Loading holdings…")
def _holdings():
    return kd.fetch_holdings()


@st.cache_data(ttl=15, show_spinner="Loading positions…")
def _positions():
    return kd.fetch_positions()


@st.cache_data(ttl=60, show_spinner="Loading indices…")
def _indices():
    return {
        "Nifty 50":   kd.index_spot("^NSEI"),
        "Bank Nifty": kd.index_spot("^NSEBANK"),
        "Sensex":     kd.index_spot("^BSESN"),
    }


def _invalidate_caches() -> None:
    _margins.clear()
    _holdings.clear()
    _positions.clear()
    _indices.clear()


with st.sidebar:
    st.subheader("Data")
    if st.button("Refresh now", type="primary", use_container_width=True):
        _invalidate_caches()
        st.rerun()
    st.caption("Cached up to ~15s for account data, ~60s for Nifty.")

    auto_refresh = st.toggle("Auto Refresh (5s)", value=False)
    if auto_refresh:
        st.caption("⚡ Auto refreshing every 5s")
        time.sleep(5)
        _invalidate_caches()
        st.rerun()

    auth.render_sidebar_kite_session(key_prefix="app")
    auth.render_logout_controls(key="kite_logout_app")

    st.divider()
    st.subheader("Setup")
    st.markdown(
        "1. In `.env` set **API_KEY** and **API_SECRET** (from the [Kite Connect](https://developers.kite.trade/) app).\n"
        "2. Set the app's **redirect URL** to `http://127.0.0.1:8765/` (or your **KITE_REDIRECT_PORT**).\n"
        "3. Use **Browser login — auto-capture** on this page, or run `python browser_login.py` from a terminal.\n"
        "4. Optional: **ACCESS_TOKEN** in `.env` is used only if `.kite_access_token` is missing; "
        "prefer browser login so the file stays in sync with **API_KEY**.\n"
        "5. **Historical data** / **Strategies** pages use **dashboard.sqlite** only (no Kite)."
    )

if not auth.ensure_kite_ready():
    st.stop()

st.title("Overview")
st.caption("Zerodha Kite snapshot with quick navigation from the sidebar.")

try:
    margins = _margins()
    holdings = _holdings()
    positions = _positions()
    indices = _indices()
except Exception as e:
    auth.handle_kite_fetch_error(e)

equity = margins.get("equity", {}) if isinstance(margins, dict) else {}
balance = equity.get("net")
available = equity.get("available", {})
utilised = equity.get("utilised", {})

# Scrolling ticker bar
ticker_items = ""
for name, data in indices.items():
    if data["price"] is not None:
        sign = "+" if data["pct"] >= 0 else ""
        color = "#1D9E75" if data["pct"] >= 0 else "#E24B4A"
        ticker_items += (
            f'<span style="margin-right:2.5rem; font-size:13px;">'
            f'<span style="color:#888; font-weight:500;">{name}</span>&nbsp;&nbsp;'
            f'<span style="font-weight:500;">₹{data["price"]:,.2f}</span>&nbsp;&nbsp;'
            f'<span style="color:{color};">{sign}{data["pct"]:.2f}%</span>'
            f'</span>'
        )

st.markdown(f"""
<div style="background:var(--secondary-background-color); border-radius:8px;
            padding:10px 16px; overflow:hidden; margin-bottom:1rem;">
  <div style="display:flex; animation: ticker 20s linear infinite; white-space:nowrap;">
    {ticker_items * 3}
  </div>
</div>
<style>
@keyframes ticker {{
  0% {{ transform: translateX(0); }}
  100% {{ transform: translateX(-33.33%); }}
}}
</style>
""", unsafe_allow_html=True)

# Index cards
ci1, ci2, ci3 = st.columns(3)
for col, (name, data) in zip([ci1, ci2, ci3], indices.items()):
    with col:
        if data["price"] is not None:
            sign = "+" if data["change"] >= 0 else ""
            delta = f"{sign}{data['change']:,.2f} ({sign}{data['pct']:.2f}%)"
            st.metric(name, f"₹ {data['price']:,.2f}", delta)
        else:
            st.metric(name, "—")

# Account metrics
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Net equity", f"₹ {float(balance):,.2f}" if balance is not None else "—")
with c2:
    st.metric("Holdings", len(holdings))
with c3:
    day_n = len(positions.get("day") or [])
    st.metric("Today's positions", day_n)

with st.expander("Equity breakdown", expanded=False):
    if isinstance(available, dict) and available:
        st.json({"available": available, "utilised": utilised})
    else:
        st.json(equity if equity else margins)

left, right = st.columns(2)

with left:
    st.subheader("Holdings preview")
    hdf = kd.holdings_dataframe(holdings)
    st.dataframe(hdf, use_container_width=True, hide_index=True, height=280)

with right:
    st.subheader("Intraday positions preview")
    pdf = kd.positions_dataframe(positions.get("day") or [])
    st.dataframe(pdf, use_container_width=True, hide_index=True, height=280)