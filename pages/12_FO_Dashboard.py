"""
F&O Dashboard
=============
Consolidated view of:
    - Portfolio Greeks (delta, theta, vega, gamma) across all open F&O positions
    - IV Rank / IV Percentile for NIFTY & BANKNIFTY
    - Futures basis (futures vs spot)
    - Expiry calendar & rollover alerts
    - Max Pain calculation
    - Open strategy P&L tracker
"""

import math
import time
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st

import kite_data as kd
from auth_streamlit import render_sidebar_kite_session

# ── constants ────────────────────────────────────────────────────────────────
INDICES = {
    "NIFTY":    {"spot_sym": "NSE:NIFTY 50",    "fno_name": "NIFTY",    "step": 50,  "lot": 50},
    "BANKNIFTY":{"spot_sym": "NSE:NIFTY BANK",  "fno_name": "BANKNIFTY","step": 100, "lot": 15},
    "FINNIFTY": {"spot_sym": "NSE:NIFTY FIN SERVICE","fno_name":"FINNIFTY","step":50,"lot": 40},
}

# ── helpers ──────────────────────────────────────────────────────────────────
def _norm_cdf(x):
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def _bs_price(S, K, T, r, sigma, opt_type="CE"):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

def _calc_iv(mkt_price, S, K, T, r=0.065, opt_type="CE") -> float:
    lo, hi = 0.001, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        p = _bs_price(S, K, T, r, mid, opt_type)
        if abs(p - mkt_price) < 0.01:
            return mid
        if p < mkt_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def _greeks(S, K, T, r, sigma, opt_type):
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
    gamma = pdf / (S * sigma * math.sqrt(T))
    vega  = S * pdf * math.sqrt(T) / 100
    if opt_type == "CE":
        delta = _norm_cdf(d1)
        theta = (-S * pdf * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-S * pdf * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "theta": round(theta, 2), "vega": round(vega, 4)}


@st.cache_data(ttl=60)
def _get_spot_prices() -> dict[str, float]:
    try:
        kite  = kd.kite_client()
        syms  = [v["spot_sym"] for v in INDICES.values()]
        q     = kite.quote(syms)
        result = {}
        for name, meta in INDICES.items():
            ltp = q.get(meta["spot_sym"], {}).get("last_price", 0)
            result[name] = ltp
        return result
    except Exception:
        return {k: 0 for k in INDICES}


@st.cache_data(ttl=120)
def _get_instruments() -> pd.DataFrame:
    try:
        kite = kd.kite_client()
        df   = pd.DataFrame(kite.instruments("NFO"))
        df["expiry"] = pd.to_datetime(df["expiry"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def _get_positions() -> pd.DataFrame:
    try:
        kite = kd.kite_client()
        pos  = kite.positions()
        rows = pos.get("net", []) + pos.get("day", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df[df["quantity"] != 0]
        return df
    except Exception:
        return pd.DataFrame()


def _expiry_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """Next 5 expiries per index."""
    rows = []
    now  = pd.Timestamp.now()
    for name in INDICES:
        sub = df[(df["name"] == name) & (df["expiry"] > now)]["expiry"].unique()
        for exp in sorted(sub)[:5]:
            d = pd.Timestamp(exp).date()
            days = (d - date.today()).days
            rows.append({"Index": name, "Expiry": d, "Days": days,
                         "Type": "Weekly" if days <= 7 else "Monthly"})
    return pd.DataFrame(rows).sort_values("Days")


def _max_pain(df: pd.DataFrame, name: str, expiry: date, spot: float) -> float:
    """Max pain = strike where total option writers' loss is minimised."""
    sub = df[(df["name"] == name) & (df["expiry"] == pd.Timestamp(expiry))].copy()
    if sub.empty:
        return spot
    strikes = sorted(sub["strike"].unique())
    # We can't fetch live OI without quotes; use instrument lot_size as proxy
    # In prod: fetch quotes and use live OI
    try:
        kite = kd.kite_client()
        ce_syms = [f"NFO:{r['tradingsymbol']}" for _, r in sub[sub["instrument_type"]=="CE"].iterrows()]
        pe_syms = [f"NFO:{r['tradingsymbol']}" for _, r in sub[sub["instrument_type"]=="PE"].iterrows()]
        tokens  = ce_syms[:200] + pe_syms[:200]
        quotes  = kite.quote(tokens) if tokens else {}
    except Exception:
        quotes = {}

    pain = {}
    for s in strikes:
        total = 0
        for strike in strikes:
            ce_row = sub[(sub["strike"] == strike) & (sub["instrument_type"] == "CE")]
            pe_row = sub[(sub["strike"] == strike) & (sub["instrument_type"] == "PE")]
            if not ce_row.empty:
                sym = f"NFO:{ce_row.iloc[0]['tradingsymbol']}"
                oi  = quotes.get(sym, {}).get("oi", 0) or 1000
                total += oi * max(s - strike, 0)
            if not pe_row.empty:
                sym = f"NFO:{pe_row.iloc[0]['tradingsymbol']}"
                oi  = quotes.get(sym, {}).get("oi", 0) or 1000
                total += oi * max(strike - s, 0)
        pain[s] = total
    return min(pain, key=pain.get)


def _iv_rank(name: str, spot: float, df: pd.DataFrame) -> dict:
    """Approx IV rank from ATM option's IV — real IV rank needs historical data."""
    try:
        exp_dates = sorted(df[(df["name"] == name) & (df["expiry"] > pd.Timestamp.now())]["expiry"].unique())
        if not exp_dates:
            return {}
        nearest  = exp_dates[0]
        step     = INDICES[name]["step"]
        atm      = round(round(spot / step) * step, 2)
        T        = max((pd.Timestamp(nearest) - pd.Timestamp.now()).total_seconds() / (365 * 86400), 1e-6)
        ce_row   = df[(df["name"] == name) & (df["expiry"] == nearest) &
                      (df["strike"] == atm) & (df["instrument_type"] == "CE")]
        if ce_row.empty:
            return {}
        kite   = kd.kite_client()
        sym    = f"NFO:{ce_row.iloc[0]['tradingsymbol']}"
        q      = kite.quote([sym])
        ltp    = q.get(sym, {}).get("last_price", 0)
        if not ltp:
            return {}
        iv = _calc_iv(ltp, spot, atm, T) * 100
        # Approximate IV rank (no historical data available without market data subscription)
        # Using static bands typical for NIFTY: low ~10%, high ~35%
        iv_low, iv_high = 10.0, 35.0
        rank = max(0, min(100, (iv - iv_low) / (iv_high - iv_low) * 100))
        return {"iv": round(iv, 1), "iv_rank": round(rank, 1), "iv_low": iv_low, "iv_high": iv_high}
    except Exception:
        return {}


# ── UI ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="F&O Dashboard", page_icon="📈", layout="wide")
render_sidebar_kite_session()
st.title("📈 F&O Dashboard")

# ── 1. Spot prices & IV Rank ──────────────────────────────────────────────────
st.subheader("🌡 Index Overview & IV Rank")

spots = _get_spot_prices()
instr = _get_instruments()

idx_cols = st.columns(len(INDICES))
for col, (name, meta) in zip(idx_cols, INDICES.items()):
    spot = spots.get(name, 0)
    with col:
        st.markdown(f"### {name}")
        st.metric("Spot", f"₹{spot:,.2f}" if spot else "N/A")
        if not instr.empty and spot:
            iv_data = _iv_rank(name, spot, instr)
            if iv_data:
                iv  = iv_data["iv"]
                ivr = iv_data["iv_rank"]
                st.metric("ATM IV", f"{iv:.1f}%")
                # IV Rank colour
                color = "#22c55e" if ivr < 30 else ("#f59e0b" if ivr < 70 else "#ef4444")
                st.markdown(
                    f"**IV Rank:** <span style='color:{color};font-size:18px'>"
                    f"**{ivr:.0f}%**</span>",
                    unsafe_allow_html=True,
                )
                st.progress(int(ivr))
                if ivr > 70:
                    st.caption("🔴 High IV — consider selling premium")
                elif ivr < 30:
                    st.caption("🟢 Low IV — consider buying options")
                else:
                    st.caption("🟡 Moderate IV")

st.divider()

# ── 2. Expiry Calendar ────────────────────────────────────────────────────────
st.subheader("📅 Expiry Calendar")

if not instr.empty:
    cal = _expiry_calendar(instr)
    if not cal.empty:
        def _cal_color(row):
            if row["Days"] <= 3:
                return ["background-color:#7f1d1d"] * len(row)
            elif row["Days"] <= 7:
                return ["background-color:#78350f"] * len(row)
            return [""] * len(row)

        cal_display = cal.copy()
        cal_display["Expiry"] = cal_display["Expiry"].astype(str)
        styled_cal = (
            cal_display.style
            .apply(_cal_color, axis=1)
            .format({"Days": "{} days"})
        )
        st.dataframe(styled_cal, use_container_width=True)

        # Rollover alerts
        urgent = cal[cal["Days"] <= 3]
        if not urgent.empty:
            for _, row in urgent.iterrows():
                st.warning(
                    f"⚠️ **{row['Index']}** expiry in **{row['Days']} days** "
                    f"({row['Expiry']}) — consider rolling positions!"
                )

st.divider()

# ── 3. Portfolio Greeks ───────────────────────────────────────────────────────
st.subheader("🔢 Portfolio Greeks")

pos_df = _get_positions()

if pos_df.empty:
    st.info("No open F&O positions found. Connect Kite and ensure positions are open.")
else:
    greeks_rows = []
    total_delta = total_gamma = total_theta = total_vega = 0

    for _, row in pos_df.iterrows():
        sym     = row.get("tradingsymbol", "")
        qty     = row.get("quantity", 0)
        ltp     = row.get("last_price", 0) or 0
        product = row.get("product", "")

        # Try to parse strike and type from tradingsymbol (e.g. NIFTY24JAN25000CE)
        opt_type = None
        strike   = 0
        T        = 0.01
        spot     = 0

        if sym.endswith("CE") or sym.endswith("PE"):
            opt_type = sym[-2:]
            # Attempt to find in instruments
            match = instr[instr["tradingsymbol"] == sym]
            if not match.empty:
                strike = match.iloc[0]["strike"]
                expiry = match.iloc[0]["expiry"].date()
                T      = max((datetime.combine(expiry, datetime.min.time()) - datetime.now()).total_seconds() / (365 * 86400), 1e-6)
                # Get underlying spot
                for idx_name, meta in INDICES.items():
                    if idx_name in sym.upper() or match.iloc[0].get("name", "") == idx_name:
                        spot = spots.get(idx_name, 0)
                        break

        if opt_type and strike and spot and ltp:
            iv = _calc_iv(ltp, spot, strike, T, opt_type=opt_type)
            g  = _greeks(spot, strike, T, 0.065, iv, opt_type)
            sign = 1 if qty > 0 else -1
            lot_qty = abs(qty)
            d = g["delta"] * lot_qty * sign
            gm = g["gamma"] * lot_qty * sign
            th = g["theta"] * lot_qty * sign
            ve = g["vega"] * lot_qty * sign
        else:
            d = gm = th = ve = 0
            iv = 0

        total_delta += d
        total_gamma += gm
        total_theta += th
        total_vega  += ve
        pnl = row.get("pnl", 0) or 0

        greeks_rows.append({
            "Symbol": sym, "Qty": qty, "LTP": ltp,
            "IV%": round(iv * 100, 1) if iv else 0,
            "Delta": round(d, 3), "Gamma": round(gm, 5),
            "Theta": round(th, 2), "Vega": round(ve, 4),
            "P&L": pnl,
        })

    g_df = pd.DataFrame(greeks_rows)

    # Portfolio totals
    tc1, tc2, tc3, tc4 = st.columns(4)
    tc1.metric("Net Delta", f"{total_delta:.2f}",
               delta="Bullish" if total_delta > 0 else "Bearish",
               delta_color="normal" if total_delta > 0 else "inverse")
    tc2.metric("Net Theta", f"{total_theta:.2f}",
               delta="Earning ₹/day" if total_theta > 0 else "Losing ₹/day",
               delta_color="normal" if total_theta > 0 else "inverse")
    tc3.metric("Net Vega", f"{total_vega:.2f}")
    tc4.metric("Net Gamma", f"{total_gamma:.4f}")

    st.dataframe(
        g_df.style.format({
            "LTP": "₹{:.2f}", "IV%": "{:.1f}%",
            "Delta": "{:.3f}", "Gamma": "{:.5f}",
            "Theta": "{:.2f}", "Vega": "{:.4f}",
            "P&L": "₹{:,.0f}",
        }),
        use_container_width=True,
    )

    # Greeks risk warnings
    if abs(total_delta) > 300:
        st.warning(f"⚠️ High net delta ({total_delta:.1f}) — large directional exposure!")
    if total_theta < -1000:
        st.warning(f"⚠️ High theta burn (₹{total_theta:.0f}/day) — time decay risk!")
    if abs(total_vega) > 500:
        st.info(f"ℹ️ Vega exposure: {total_vega:.1f} — sensitive to IV changes")

st.divider()

# ── 4. Max Pain ───────────────────────────────────────────────────────────────
st.subheader("🎯 Max Pain")

if not instr.empty:
    mp_cols = st.columns(len(INDICES))
    for col, (name, meta) in zip(mp_cols, INDICES.items()):
        spot = spots.get(name, 0)
        with col:
            if spot:
                exp_dates = sorted(
                    instr[(instr["name"] == name) & (instr["expiry"] > pd.Timestamp.now())]["expiry"].unique()
                )
                if exp_dates:
                    nearest_exp = pd.Timestamp(exp_dates[0]).date()
                    with st.spinner(f"Calculating {name} max pain..."):
                        mp = _max_pain(instr, name, nearest_exp, spot)
                    diff = mp - spot
                    st.metric(
                        f"{name} Max Pain",
                        f"₹{mp:,.0f}",
                        delta=f"{diff:+.0f} from spot",
                        delta_color="normal" if diff >= 0 else "inverse",
                    )
                    st.caption(f"Expiry: {nearest_exp}")

st.divider()

# ── 5. Futures Basis ──────────────────────────────────────────────────────────
st.subheader("📐 Futures Basis")

if not instr.empty:
    fut_cols = st.columns(len(INDICES))
    for col, (name, meta) in zip(fut_cols, INDICES.items()):
        spot = spots.get(name, 0)
        with col:
            # Find nearest futures contract
            fut_df = instr[
                (instr["name"] == name) &
                (instr["instrument_type"] == "FUT") &
                (instr["expiry"] > pd.Timestamp.now())
            ]
            if not fut_df.empty and spot:
                nearest_fut = fut_df.sort_values("expiry").iloc[0]
                try:
                    kite    = kd.kite_client()
                    sym     = f"NFO:{nearest_fut['tradingsymbol']}"
                    q       = kite.quote([sym])
                    fut_ltp = q.get(sym, {}).get("last_price", 0)
                    basis   = fut_ltp - spot
                    basis_p = (basis / spot) * 100
                    exp_d   = pd.Timestamp(nearest_fut["expiry"]).date()
                    ann_basis = basis_p / max((exp_d - date.today()).days, 1) * 365

                    st.metric(name, f"₹{fut_ltp:,.2f}",
                              delta=f"Basis: {basis:+.2f} ({basis_p:+.2f}%)",
                              delta_color="normal" if basis >= 0 else "inverse")
                    st.caption(f"Annualised: {ann_basis:.1f}% | Exp: {exp_d}")
                except Exception as e:
                    st.caption(f"Futures data unavailable: {e}")

# ── auto refresh ──────────────────────────────────────────────────────────────
st.divider()
st.caption(f"⏱ Last updated: {datetime.now().strftime('%H:%M:%S')} — refreshes every 60 s")
if st.toggle("Auto Refresh (60s)", value=True, key="fo_refresh"):
    time.sleep(60)
    st.rerun()
