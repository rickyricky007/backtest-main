"""
Options Chain Viewer — All F&O Indices & Stocks
================================================
Real-time options chain for any NSE F&O underlying.

Features:
    - All F&O indices + ~180 stocks (searchable dropdown)
    - ATM highlighted in gold
    - CE / PE columns side-by-side
    - OI, Volume, IV, Delta, Theta, Vega per strike
    - PCR (Put-Call Ratio) gauge
    - OI bar chart — see support/resistance by OI
    - One-click straddle / strangle launch (paper mode)
    - Auto-refresh every 30 s
"""

from __future__ import annotations

import math
import time
from datetime import datetime, date

import pandas as pd
import streamlit as st

import kite_data as kd
from auth_streamlit import render_sidebar_kite_session
from fo_symbols import FO_INDICES, FO_STOCKS, ALL_FO_SYMBOLS
from logger import get_logger

log = get_logger("options_chain")

# ── Strike step per underlying ────────────────────────────────────────────────
# NSE standard strike intervals
STRIKE_STEP: dict[str, int] = {
    "NIFTY":        50,
    "NIFTY 50":     50,
    "BANKNIFTY":    100,
    "BANK NIFTY":   100,
    "FINNIFTY":     50,
    "MIDCPNIFTY":   25,
    "MIDCAP NIFTY": 25,
    "SENSEX":       100,
    "BANKEX":       100,
}
DEFAULT_STEP = 50   # for stocks

# ── Kite underlying name → NFO instrument `name` field mapping ────────────────
KITE_NAME_MAP: dict[str, str] = {
    "NIFTY 50":     "NIFTY",
    "BANK NIFTY":   "BANKNIFTY",
    "FINNIFTY":     "FINNIFTY",
    "MIDCAP NIFTY": "MIDCPNIFTY",
    "SENSEX":       "SENSEX",
    "BANKEX":       "BANKEX",
}

# ── Black-Scholes helpers ─────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, opt_type: str = "CE") -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _calc_iv(market_price: float, S: float, K: float, T: float, r: float = 0.065, opt_type: str = "CE") -> float:
    """Bisection IV solver (returns fraction, e.g. 0.20 = 20%)."""
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
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


def _calc_greeks(S: float, K: float, T: float, r: float, sigma: float, opt_type: str = "CE") -> dict:
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
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


# ── Data fetchers ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _load_instruments(exchange: str = "NFO") -> pd.DataFrame:
    try:
        kite = kd.kite_client()
        instr = kite.instruments(exchange)
        df = pd.DataFrame(instr)
        df["expiry"] = pd.to_datetime(df["expiry"])
        log.info(f"Loaded {len(df)} instruments from {exchange}")
        return df
    except Exception:
        log.error("Instrument load error", exc_info=True)
        return pd.DataFrame()


@st.cache_data(ttl=15)
def _get_spot(symbol: str, is_index: bool) -> float:
    """Fetch spot price for index or stock."""
    try:
        kite = kd.kite_client()
        if is_index:
            # Indices use their Kite key
            from fo_symbols import FO_INDICES
            key = FO_INDICES.get(symbol)
            if not key:
                return 0.0
            q = kite.quote([key])
            return q[key]["last_price"]
        else:
            key = f"NSE:{symbol}"
            q = kite.quote([key])
            return q[key]["last_price"]
    except Exception:
        log.warning(f"Could not fetch spot for {symbol}", exc_info=False)
        return 0.0


def _get_expiries(df: pd.DataFrame, nfo_name: str) -> list[date]:
    """Return available expiry dates for a given NFO underlying name."""
    try:
        sub = df[(df["name"] == nfo_name) & (df["expiry"] >= pd.Timestamp.now())]
        dates = sorted(sub["expiry"].unique())
        return [pd.Timestamp(d).date() for d in dates]
    except Exception:
        log.error("Expiry fetch error", exc_info=True)
        return []


def _build_chain(
    df: pd.DataFrame,
    nfo_name: str,
    expiry: date,
    spot: float,
    num_strikes: int = 20,
) -> pd.DataFrame:
    """Build full options chain dataframe with Greeks."""
    try:
        sub = df[
            (df["name"] == nfo_name) &
            (df["expiry"] == pd.Timestamp(expiry))
        ].copy()

        if sub.empty:
            log.warning(f"No instruments for {nfo_name} exp={expiry}")
            return pd.DataFrame()

        strikes = sorted(sub["strike"].unique())
        atm     = min(strikes, key=lambda x: abs(x - spot))
        idx     = strikes.index(atm)
        lo_idx  = max(0, idx - num_strikes // 2)
        hi_idx  = min(len(strikes), idx + num_strikes // 2 + 1)
        strikes = strikes[lo_idx:hi_idx]

        T = max(
            (datetime.combine(expiry, datetime.min.time()) - datetime.now()).total_seconds()
            / (365 * 86400), 1e-6
        )
        r = 0.065  # risk-free rate

        # ── Batch quote ───────────────────────────────────────────────────────
        relevant = sub[sub["strike"].isin(strikes)]
        tokens = [
            f"NFO:{row['tradingsymbol']}"
            for _, row in relevant.iterrows()
        ]
        quotes: dict = {}
        if tokens:
            try:
                kite = kd.kite_client()
                for i in range(0, len(tokens), 200):
                    batch = tokens[i:i+200]
                    quotes.update(kite.quote(batch))
            except Exception:
                log.warning("Quote batch error", exc_info=False)

        # ── Build rows ────────────────────────────────────────────────────────
        rows = []
        for strike in strikes:
            ce_row = sub[(sub["strike"] == strike) & (sub["instrument_type"] == "CE")]
            pe_row = sub[(sub["strike"] == strike) & (sub["instrument_type"] == "PE")]

            def _extract(opt_row: pd.DataFrame, opt_type: str) -> dict:
                if opt_row.empty:
                    return {}
                sym = opt_row.iloc[0]["tradingsymbol"]
                key = f"NFO:{sym}"
                q   = quotes.get(key, {})
                ltp = q.get("last_price", 0) or 0
                oi  = q.get("oi", 0) or 0
                oi_d = q.get("oi_day_high", 0) - q.get("oi_day_low", 0)
                vol = q.get("volume", 0) or 0
                bid = ((q.get("depth", {}).get("buy") or [{}])[0]).get("price", 0)
                ask = ((q.get("depth", {}).get("sell") or [{}])[0]).get("price", 0)
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
                "CE_Symbol": ce.get("symbol", ""),
                "CE_LTP":    ce.get("ltp", 0),
                "CE_IV":     ce.get("iv", 0),
                "CE_OI":     ce.get("oi", 0),
                "CE_Vol":    ce.get("vol", 0),
                "CE_Delta":  ce.get("delta", 0),
                "CE_Theta":  ce.get("theta", 0),
                "CE_Vega":   ce.get("vega", 0),
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

    except Exception:
        log.error("Build chain error", exc_info=True)
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Options Chain", page_icon="📊", layout="wide")
render_sidebar_kite_session()

st.title("📊 Options Chain — All F&O Indices & Stocks")
st.caption("Live options chain with Greeks, PCR and OI charts for any NSE F&O underlying")

# ── Underlying selector ───────────────────────────────────────────────────────
INDEX_NAMES   = list(FO_INDICES.keys())                 # e.g. "NIFTY 50"
STOCK_NAMES   = FO_STOCKS                               # plain symbols like "RELIANCE"
ALL_CHOICES   = INDEX_NAMES + STOCK_NAMES

col_sym, col_exp, col_strikes, col_refresh = st.columns([3, 2, 1, 1])

with col_sym:
    underlying = st.selectbox(
        "Underlying (type to search)",
        ALL_CHOICES,
        index=0,
        help="Select any F&O index or stock"
    )

# Determine NFO instrument name and whether this is an index
_is_index = underlying in INDEX_NAMES
nfo_name  = KITE_NAME_MAP.get(underlying, underlying)   # stocks: same name

# ── Load instruments (cached) ─────────────────────────────────────────────────
instruments_df = _load_instruments("NFO")

# BSE instruments needed for SENSEX/BANKEX
bse_df = pd.DataFrame()
if underlying in ("SENSEX", "BANKEX"):
    bse_df = _load_instruments("BFO")
    combo_df = pd.concat([instruments_df, bse_df], ignore_index=True) if not bse_df.empty else instruments_df
else:
    combo_df = instruments_df

expiries = _get_expiries(combo_df, nfo_name) if not combo_df.empty else []

with col_exp:
    if expiries:
        expiry = st.selectbox(
            "Expiry",
            expiries,
            format_func=lambda d: d.strftime("%d %b %Y")
        )
    else:
        st.warning("No expiries — check Kite connection")
        st.stop()

with col_strikes:
    num_strikes = st.selectbox("Strikes ±", [10, 20, 30, 40], index=1)

with col_refresh:
    auto_refresh = st.toggle("Auto 30s", value=True)

# ── Spot price ────────────────────────────────────────────────────────────────
spot = _get_spot(underlying, _is_index)
if spot == 0:
    st.error("❌ Could not fetch spot price — is Kite connected and token valid?")
    st.stop()

days_to_exp = (datetime.combine(expiry, datetime.min.time()) - datetime.now()).days

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Underlying", underlying)
m2.metric("Spot Price",  f"₹{spot:,.2f}")
m3.metric("Days to Expiry", days_to_exp)
m4.metric("Expiry",     expiry.strftime("%d %b %Y"))
m5.metric("Type",       "Index" if _is_index else "Stock")

st.divider()

# ── Build chain ───────────────────────────────────────────────────────────────
with st.spinner(f"Loading options chain for {underlying}..."):
    chain = _build_chain(combo_df, nfo_name, expiry, spot, num_strikes)

if chain.empty:
    st.error(
        f"No chain data for **{underlying}** (NFO name: `{nfo_name}`). "
        "Check Kite connection and that this symbol has active options."
    )
    st.stop()

# ── PCR & summary metrics ─────────────────────────────────────────────────────
total_ce_oi = chain["CE_OI"].sum()
total_pe_oi = chain["PE_OI"].sum()
pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 0

atm_row = chain[chain["ATM"]]

p1, p2, p3, p4, p5 = st.columns(5)
p1.metric(
    "PCR (OI)", pcr,
    delta="Bearish" if pcr < 0.8 else ("Bullish" if pcr > 1.2 else "Neutral"),
    delta_color="inverse" if pcr < 0.8 else "normal",
    help="Put-Call Ratio. >1.2 = bearish sentiment (contrarian bullish). <0.8 = bullish sentiment (contrarian bearish)."
)
p2.metric("Total CE OI", f"{total_ce_oi:,.0f}")
p3.metric("Total PE OI", f"{total_pe_oi:,.0f}")

if not atm_row.empty:
    atm_iv = (atm_row.iloc[0]["CE_IV"] + atm_row.iloc[0]["PE_IV"]) / 2
    straddle_cost = atm_row.iloc[0]["CE_LTP"] + atm_row.iloc[0]["PE_LTP"]
    p4.metric("ATM IV", f"{atm_iv:.1f}%", help="Average of ATM CE and PE IV")
    p5.metric("ATM Straddle", f"₹{straddle_cost:.2f}", help="CE + PE premium at ATM strike")

st.divider()

# ── Main tabs ─────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Options Chain", "📊 OI Chart", "⚡ Strategy Launcher"])

# ── TAB 1: Options Chain Table ────────────────────────────────────────────────
with tab1:
    st.subheader(f"Options Chain — {underlying} | Expiry: {expiry.strftime('%d %b %Y')}")

    # ATM highlight
    def _highlight_atm(row):
        if row.get("ATM", False):
            return ["background-color: #3d3200; color: #ffd700; font-weight: bold"] * len(row)
        return [""] * len(row)

    display_cols = [
        "CE_LTP", "CE_IV", "CE_OI", "CE_Vol", "CE_Delta", "CE_Theta",
        "Strike",
        "PE_Delta", "PE_Theta", "PE_OI", "PE_Vol", "PE_IV", "PE_LTP",
    ]
    display = chain[["ATM"] + display_cols].copy()

    try:
        styled = (
            display.style
            .apply(_highlight_atm, axis=1)
            .format({
                "CE_LTP":   "₹{:.2f}",  "PE_LTP":   "₹{:.2f}",
                "CE_IV":    "{:.1f}%",   "PE_IV":    "{:.1f}%",
                "CE_OI":    "{:,.0f}",   "PE_OI":    "{:,.0f}",
                "CE_Vol":   "{:,.0f}",   "PE_Vol":   "{:,.0f}",
                "CE_Delta": "{:.3f}",    "PE_Delta": "{:.3f}",
                "CE_Theta": "{:.2f}",    "PE_Theta": "{:.2f}",
                "Strike":   "₹{:,.0f}",
                "ATM":      lambda v: "★ ATM" if v else "",
            })
        )
        st.dataframe(styled, use_container_width=True, height=600)
    except Exception:
        # Fallback without styling (if jinja2 not installed)
        st.dataframe(display, use_container_width=True, height=600)
        st.caption("ℹ️ Install jinja2 for colour highlighting: `pip install jinja2`")

    # Download
    csv = chain.to_csv(index=False)
    st.download_button(
        "⬇️ Download Chain CSV", csv,
        file_name=f"options_chain_{underlying}_{expiry}.csv",
        mime="text/csv"
    )

# ── TAB 2: OI Chart ───────────────────────────────────────────────────────────
with tab2:
    st.subheader("Open Interest by Strike — Support & Resistance Zones")
    st.caption("High CE OI = resistance zone | High PE OI = support zone")

    oi_chart = chain[["Strike", "CE_OI", "PE_OI"]].copy()
    oi_chart = oi_chart.rename(columns={"CE_OI": "CE OI (Resistance)", "PE_OI": "PE OI (Support)"})
    oi_chart = oi_chart.set_index("Strike")
    st.bar_chart(oi_chart, color=["#ef4444", "#22c55e"], height=450)

    # PCR per strike
    st.subheader("PCR by Strike")
    chain_pcr = chain.copy()
    chain_pcr["PCR"] = chain_pcr.apply(
        lambda r: round(r["PE_OI"] / r["CE_OI"], 2) if r["CE_OI"] > 0 else 0,
        axis=1
    )
    pcr_display = chain_pcr[["Strike", "CE_OI", "PE_OI", "PCR"]].copy()
    pcr_display["Strike"] = pcr_display["Strike"].apply(lambda x: f"₹{x:,.0f}")
    st.dataframe(pcr_display, use_container_width=True, hide_index=True)

# ── TAB 3: Strategy Launcher ──────────────────────────────────────────────────
with tab3:
    st.subheader("⚡ Quick Strategy Launcher (Paper Mode)")

    if atm_row.empty:
        st.warning("Could not determine ATM strike.")
    else:
        atm_strike = atm_row.iloc[0]["Strike"]
        ce_symbol  = atm_row.iloc[0]["CE_Symbol"]
        pe_symbol  = atm_row.iloc[0]["PE_Symbol"]
        ce_ltp     = atm_row.iloc[0]["CE_LTP"]
        pe_ltp     = atm_row.iloc[0]["PE_LTP"]

        step = STRIKE_STEP.get(underlying, DEFAULT_STEP)

        strat_cols = st.columns(3)

        # Short Straddle
        with strat_cols[0]:
            st.markdown("### 🔴 Short Straddle")
            st.caption("Sell ATM CE + ATM PE — profit from time decay")
            st.metric("ATM Strike",         f"₹{atm_strike:,.0f}")
            st.metric("CE Sold",            f"₹{ce_ltp:.2f}")
            st.metric("PE Sold",            f"₹{pe_ltp:.2f}")
            st.metric("Premium Collected",  f"₹{ce_ltp + pe_ltp:.2f}")
            st.caption(f"Break-even: ₹{atm_strike - ce_ltp - pe_ltp:,.0f} / ₹{atm_strike + ce_ltp + pe_ltp:,.0f}")
            if st.button("📄 Paper Short Straddle", key="paper_straddle"):
                st.success(f"✅ Paper: Short Straddle at ₹{atm_strike:.0f} | Premium ₹{ce_ltp+pe_ltp:.2f}")

        # Short Strangle (OTM)
        with strat_cols[1]:
            otm_steps = 2
            otm_call_strike = atm_strike + otm_steps * step
            otm_put_strike  = atm_strike - otm_steps * step
            otm_ce_row = chain[chain["Strike"] == otm_call_strike]
            otm_pe_row = chain[chain["Strike"] == otm_put_strike]

            st.markdown("### 🟠 Short Strangle")
            st.caption(f"Sell OTM CE ({otm_steps} steps) + OTM PE ({otm_steps} steps)")
            if not otm_ce_row.empty and not otm_pe_row.empty:
                otm_ce_ltp = otm_ce_row.iloc[0]["CE_LTP"]
                otm_pe_ltp = otm_pe_row.iloc[0]["PE_LTP"]
                st.metric("CE Strike",           f"₹{otm_call_strike:,.0f}")
                st.metric("PE Strike",           f"₹{otm_put_strike:,.0f}")
                st.metric("Premium Collected",   f"₹{otm_ce_ltp + otm_pe_ltp:.2f}")
                if st.button("📄 Paper Short Strangle", key="paper_strangle"):
                    st.success(f"✅ Paper: Short Strangle CE@{otm_call_strike:.0f} PE@{otm_put_strike:.0f}")
            else:
                st.info("OTM strikes not in loaded range — increase Strikes ±")

        # Long Straddle
        with strat_cols[2]:
            st.markdown("### 🟢 Long Straddle")
            st.caption("Buy ATM CE + ATM PE — profit from big moves")
            st.metric("ATM Strike",   f"₹{atm_strike:,.0f}")
            st.metric("CE Bought",    f"₹{ce_ltp:.2f}")
            st.metric("PE Bought",    f"₹{pe_ltp:.2f}")
            st.metric("Max Risk",     f"₹{ce_ltp + pe_ltp:.2f} per lot")
            st.caption(f"Break-even: ₹{atm_strike - ce_ltp - pe_ltp:,.0f} / ₹{atm_strike + ce_ltp + pe_ltp:,.0f}")
            if st.button("📄 Paper Long Straddle", key="paper_long_straddle"):
                st.success(f"✅ Paper: Long Straddle at ₹{atm_strike:.0f} | Cost ₹{ce_ltp+pe_ltp:.2f}")

# ── Auto refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    st.divider()
    st.caption(f"⏱ Last updated: {datetime.now().strftime('%H:%M:%S')} — auto-refreshing every 30s")
    time.sleep(30)
    st.rerun()
