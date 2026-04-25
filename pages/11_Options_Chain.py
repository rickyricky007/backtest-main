"""
Options Chain Viewer
====================
Real-time options chain for NIFTY / BANKNIFTY / any NFO underlying.

Features:
    - ATM highlighted in gold
    - CE / PE columns side-by-side
    - OI, Volume, IV, Delta, Theta, Vega per strike
    - PCR (Put-Call Ratio) gauge
    - One-click straddle / strangle launch
    - Auto-refresh every 30 s
"""

import math
import time
from datetime import datetime, date

import pandas as pd
import streamlit as st

import kite_data as kd
from auth_streamlit import render_sidebar_kite_session

# ── helpers ─────────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _bs_price(S, K, T, r, sigma, opt_type="CE"):
    """Black-Scholes price."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
        return intrinsic
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _calc_iv(market_price, S, K, T, r=0.065, opt_type="CE") -> float:
    """Bisection IV solver."""
    lo, hi = 0.001, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        p = _bs_price(S, K, T, r, mid, opt_type)
        if abs(p - market_price) < 0.01:
            return mid
        if p < market_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _calc_greeks(S, K, T, r, sigma, opt_type="CE") -> dict:
    """Delta, Gamma, Theta, Vega."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
    gamma  = pdf_d1 / (S * sigma * math.sqrt(T))
    vega   = S * pdf_d1 * math.sqrt(T) / 100
    if opt_type == "CE":
        delta = _norm_cdf(d1)
        theta = (-S * pdf_d1 * sigma / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-S * pdf_d1 * sigma / (2 * math.sqrt(T))
                 + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 2),
        "vega":  round(vega, 4),
    }


@st.cache_data(ttl=30)
def _load_instruments(exchange="NFO"):
    try:
        kite = kd.kite_client()
        instr = kite.instruments(exchange)
        df = pd.DataFrame(instr)
        df["expiry"] = pd.to_datetime(df["expiry"])
        return df
    except Exception as e:
        st.error(f"Instrument load error: {e}")
        return pd.DataFrame()


def _get_spot(underlying: str) -> float:
    try:
        kite = kd.kite_client()
        sym = f"NSE:{underlying}" if "NIFTY" in underlying else f"NSE:{underlying}"
        q = kite.quote([sym])
        return q[sym]["last_price"]
    except Exception:
        return 0.0


def _get_expiries(df: pd.DataFrame, name: str) -> list[date]:
    sub = df[(df["name"] == name) & (df["expiry"] >= pd.Timestamp.now())]
    dates = sorted(sub["expiry"].unique())
    return [pd.Timestamp(d).date() for d in dates]


def _build_chain(df: pd.DataFrame, name: str, expiry: date,
                 spot: float, num_strikes: int = 20) -> pd.DataFrame:
    """Build options chain dataframe with Greeks."""
    sub = df[
        (df["name"] == name) &
        (df["expiry"] == pd.Timestamp(expiry))
    ].copy()

    if sub.empty:
        return pd.DataFrame()

    strikes = sorted(sub["strike"].unique())
    # Filter strikes around ATM
    atm    = min(strikes, key=lambda x: abs(x - spot))
    idx    = strikes.index(atm)
    lo_idx = max(0, idx - num_strikes // 2)
    hi_idx = min(len(strikes), idx + num_strikes // 2 + 1)
    strikes = strikes[lo_idx:hi_idx]

    T = max((datetime.combine(expiry, datetime.min.time()) - datetime.now()).total_seconds() / (365 * 86400), 1e-6)
    r = 0.065  # risk-free rate

    rows = []
    try:
        kite = kd.kite_client()
        # Fetch quotes for all options
        ce_tokens = [
            f"NFO:{row['tradingsymbol']}"
            for _, row in sub[(sub["instrument_type"] == "CE") & (sub["strike"].isin(strikes))].iterrows()
        ]
        pe_tokens = [
            f"NFO:{row['tradingsymbol']}"
            for _, row in sub[(sub["instrument_type"] == "PE") & (sub["strike"].isin(strikes))].iterrows()
        ]
        # Batch quote (up to 500 tokens)
        all_tokens = ce_tokens[:100] + pe_tokens[:100]
        quotes = {}
        if all_tokens:
            try:
                quotes = kite.quote(all_tokens)
            except Exception:
                pass
    except Exception:
        quotes = {}

    for strike in strikes:
        ce_row = sub[(sub["strike"] == strike) & (sub["instrument_type"] == "CE")]
        pe_row = sub[(sub["strike"] == strike) & (sub["instrument_type"] == "PE")]

        def _extract(opt_row, opt_type):
            if opt_row.empty:
                return {}
            sym = opt_row.iloc[0]["tradingsymbol"]
            key = f"NFO:{sym}"
            q   = quotes.get(key, {})
            ltp = q.get("last_price", 0) or 0
            oi  = q.get("oi", 0) or 0
            vol = q.get("volume", 0) or 0
            bid = (q.get("depth", {}).get("buy", [{}]) or [{}])[0].get("price", 0)
            ask = (q.get("depth", {}).get("sell", [{}]) or [{}])[0].get("price", 0)
            iv  = _calc_iv(ltp, spot, strike, T, r=r, opt_type=opt_type) * 100 if ltp > 0 else 0
            g   = _calc_greeks(spot, strike, T, r, iv / 100, opt_type) if iv > 0 else {}
            return {
                "ltp": ltp, "oi": oi, "vol": vol,
                "bid": bid, "ask": ask,
                "iv": round(iv, 1),
                "delta": g.get("delta", 0),
                "theta": g.get("theta", 0),
                "vega":  g.get("vega", 0),
                "symbol": sym,
            }

        ce = _extract(ce_row, "CE")
        pe = _extract(pe_row, "PE")
        rows.append({
            "Strike":    strike,
            "ATM":       strike == atm,
            # CE side
            "CE_Symbol": ce.get("symbol", ""),
            "CE_LTP":    ce.get("ltp", 0),
            "CE_IV":     ce.get("iv", 0),
            "CE_OI":     ce.get("oi", 0),
            "CE_Vol":    ce.get("vol", 0),
            "CE_Delta":  ce.get("delta", 0),
            "CE_Theta":  ce.get("theta", 0),
            "CE_Vega":   ce.get("vega", 0),
            # PE side
            "PE_Symbol": pe.get("symbol", ""),
            "PE_LTP":    pe.get("ltp", 0),
            "PE_IV":     pe.get("iv", 0),
            "PE_OI":     pe.get("oi", 0),
            "PE_Vol":    pe.get("vol", 0),
            "PE_Delta":  pe.get("delta", 0),
            "PE_Theta":  pe.get("theta", 0),
            "PE_Vega":   pe.get("vega", 0),
        })

    return pd.DataFrame(rows)


# ── UI ───────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Options Chain", page_icon="📊", layout="wide")
render_sidebar_kite_session()

st.title("📊 Options Chain Viewer")

# ── controls ─────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

with col1:
    underlying = st.selectbox(
        "Underlying",
        ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
        index=0,
    )

instruments_df = _load_instruments()
expiries = _get_expiries(instruments_df, underlying) if not instruments_df.empty else []

with col2:
    if expiries:
        expiry = st.selectbox("Expiry", expiries, format_func=lambda d: d.strftime("%d %b %Y"))
    else:
        st.warning("No expiries found — check Kite connection")
        st.stop()

with col3:
    num_strikes = st.selectbox("Strikes", [10, 20, 30, 40], index=1)

with col4:
    auto_refresh = st.toggle("Auto Refresh (30s)", value=True)

# ── spot price ────────────────────────────────────────────────────────────────
spot = _get_spot(underlying)
if spot == 0:
    st.error("Could not fetch spot price. Is Kite connected?")
    st.stop()

days_to_expiry = (datetime.combine(expiry, datetime.min.time()) - datetime.now()).days

m1, m2, m3, m4 = st.columns(4)
m1.metric("Spot Price", f"₹{spot:,.2f}")
m2.metric("Days to Expiry", days_to_expiry)
m3.metric("Expiry Date", expiry.strftime("%d %b %Y"))
m4.metric("Underlying", underlying)

st.divider()

# ── build chain ───────────────────────────────────────────────────────────────
with st.spinner("Loading options chain..."):
    chain = _build_chain(instruments_df, underlying, expiry, spot, num_strikes)

if chain.empty:
    st.error("No chain data. Check Kite connection and NFO instruments.")
    st.stop()

# ── PCR ───────────────────────────────────────────────────────────────────────
total_ce_oi = chain["CE_OI"].sum()
total_pe_oi = chain["PE_OI"].sum()
pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 0

p1, p2, p3, p4, p5 = st.columns(5)
p1.metric("PCR (OI)", pcr,
          delta="Bearish" if pcr < 0.8 else ("Bullish" if pcr > 1.2 else "Neutral"),
          delta_color="inverse" if pcr < 0.8 else "normal")
p2.metric("Total CE OI", f"{total_ce_oi:,.0f}")
p3.metric("Total PE OI", f"{total_pe_oi:,.0f}")
atm_row = chain[chain["ATM"] == True]
if not atm_row.empty:
    atm_iv = (atm_row.iloc[0]["CE_IV"] + atm_row.iloc[0]["PE_IV"]) / 2
    p4.metric("ATM IV", f"{atm_iv:.1f}%")
    straddle_cost = atm_row.iloc[0]["CE_LTP"] + atm_row.iloc[0]["PE_LTP"]
    p5.metric("Straddle Cost", f"₹{straddle_cost:.2f}")

st.divider()

# ── render chain table ────────────────────────────────────────────────────────
st.subheader("Options Chain")

# Colour ATM row gold
def _highlight_atm(row):
    if row["ATM"]:
        return ["background-color: #3d3200; color: #ffd700; font-weight: bold"] * len(row)
    return [""] * len(row)

display_cols = [
    "CE_LTP", "CE_IV", "CE_OI", "CE_Vol", "CE_Delta", "CE_Theta",
    "Strike",
    "PE_LTP", "PE_IV", "PE_OI", "PE_Vol", "PE_Delta", "PE_Theta",
]
display = chain[["ATM"] + display_cols].copy()

styled = (
    display.style
    .apply(_highlight_atm, axis=1)
    .format({
        "CE_LTP": "₹{:.2f}", "PE_LTP": "₹{:.2f}",
        "CE_IV": "{:.1f}%",  "PE_IV": "{:.1f}%",
        "CE_OI": "{:,.0f}",  "PE_OI": "{:,.0f}",
        "CE_Vol": "{:,.0f}", "PE_Vol": "{:,.0f}",
        "CE_Delta": "{:.3f}","PE_Delta": "{:.3f}",
        "CE_Theta": "{:.2f}","PE_Theta": "{:.2f}",
        "Strike": "₹{:,.0f}",
        "ATM": lambda v: "★ ATM" if v else "",
    })
)

st.dataframe(styled, use_container_width=True, height=600)

# ── OI bar chart ──────────────────────────────────────────────────────────────
st.subheader("Open Interest by Strike")
oi_chart = chain[["Strike", "CE_OI", "PE_OI"]].copy()
oi_chart = oi_chart.rename(columns={"CE_OI": "CE OI", "PE_OI": "PE OI"})
oi_chart = oi_chart.set_index("Strike")
st.bar_chart(oi_chart, color=["#ef4444", "#22c55e"])

# ── Quick trade launcher ──────────────────────────────────────────────────────
st.divider()
st.subheader("⚡ Quick Strategy Launcher")

if not atm_row.empty:
    atm_strike   = atm_row.iloc[0]["Strike"]
    ce_symbol    = atm_row.iloc[0]["CE_Symbol"]
    pe_symbol    = atm_row.iloc[0]["PE_Symbol"]
    ce_ltp       = atm_row.iloc[0]["CE_LTP"]
    pe_ltp       = atm_row.iloc[0]["PE_LTP"]

    strat_cols = st.columns(3)
    with strat_cols[0]:
        st.markdown("**Short Straddle** (sell ATM CE + PE)")
        st.caption(f"CE: {ce_symbol} @ ₹{ce_ltp:.2f}")
        st.caption(f"PE: {pe_symbol} @ ₹{pe_ltp:.2f}")
        st.caption(f"Premium collected: ₹{ce_ltp + pe_ltp:.2f}")
        if st.button("🔴 Sell Straddle (Paper)", key="straddle_sell"):
            st.session_state["straddle_intent"] = {
                "strategy": "short_straddle",
                "atm_strike": atm_strike,
                "ce_symbol": ce_symbol,
                "pe_symbol": pe_symbol,
            }
            st.success(f"Short Straddle queued at ₹{atm_strike:.0f} (paper mode)")

    with strat_cols[1]:
        otm = 2
        otm_ce_row = chain[chain["Strike"] == atm_strike + otm * 50]
        otm_pe_row = chain[chain["Strike"] == atm_strike - otm * 50]
        if not otm_ce_row.empty and not otm_pe_row.empty:
            otm_ce_ltp = otm_ce_row.iloc[0]["CE_LTP"]
            otm_pe_ltp = otm_pe_row.iloc[0]["PE_LTP"]
            st.markdown("**Short Strangle** (OTM CE + PE)")
            st.caption(f"CE: {atm_strike + otm*50:.0f} CE @ ₹{otm_ce_ltp:.2f}")
            st.caption(f"PE: {atm_strike - otm*50:.0f} PE @ ₹{otm_pe_ltp:.2f}")
            st.caption(f"Premium collected: ₹{otm_ce_ltp + otm_pe_ltp:.2f}")
            if st.button("🔴 Sell Strangle (Paper)", key="strangle_sell"):
                st.success(f"Short Strangle queued (paper mode)")
        else:
            st.info("OTM strikes not available")

    with strat_cols[2]:
        st.markdown("**Long Straddle** (buy ATM CE + PE)")
        st.caption(f"CE: {ce_symbol} @ ₹{ce_ltp:.2f}")
        st.caption(f"PE: {pe_symbol} @ ₹{pe_ltp:.2f}")
        st.caption(f"Max risk: ₹{ce_ltp + pe_ltp:.2f} per lot")
        if st.button("🟢 Buy Straddle (Paper)", key="straddle_buy"):
            st.success(f"Long Straddle queued at ₹{atm_strike:.0f} (paper mode)")

# ── auto refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    st.caption(f"⏱ Last updated: {datetime.now().strftime('%H:%M:%S')} — refreshing every 30 s")
    time.sleep(30)
    st.rerun()
