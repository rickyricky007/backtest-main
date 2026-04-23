"""RSI Strategy Scanner — Complete Clean System"""

from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import datetime
import time

import auth_streamlit as auth
import kite_data as kd
from rsi_strategy import run_rsi_scanner_multi_tf

st.set_page_config(page_title="RSI Strategy Pro", layout="wide")
auth.render_auth_cleared_banner()

if not auth.ensure_kite_ready():
    st.stop()

st.title("📊 RSI Strategy (Full System)")
st.caption("Signals → Trades → Risk → Exit → P&L")

# ── CONFIG ────────────────────────────────────────────────────────────────
CAPITAL_PER_TRADE = 10000  # ₹10k per trade

# ── STATE ────────────────────────────────────────────────────────────────
for key in ["signals", "trades"]:
    if key not in st.session_state:
        st.session_state[key] = []

# ── HELPERS ──────────────────────────────────────────────────────────────
def safe_kite(func, *args):
    try:
        return func(*args)
    except:
        return None

def calculate_pnl(trade, ltp):
    if trade["side"] == "BUY":
        return (ltp - trade["entry"]) * trade["qty"]
    else:
        return (trade["entry"] - ltp) * trade["qty"]

# ── TRADE ENGINE ─────────────────────────────────────────────────────────
def create_trade(signal):
    entry = signal["price"]
    qty = int(CAPITAL_PER_TRADE / entry)

    if signal["side"] == "BUY":
        sl = entry * 0.98
        target = entry * 1.04
    else:
        sl = entry * 1.02
        target = entry * 0.96

    return {
        "symbol": signal["symbol"],
        "side": signal["side"],
        "entry": entry,
        "qty": qty,
        "sl": round(sl, 2),
        "target": round(target, 2),
        "status": "OPEN",
        "entry_time": signal["time"],
        "exit_price": None,
        "pnl": 0,
    }

def update_trades():
    kite = st.session_state.get("kite")

    for t in st.session_state["trades"]:
        if t["status"] != "OPEN":
            continue

        ltp = safe_kite(kd.get_ltp, kite, t["symbol"])
        if not ltp:
            continue

        t["pnl"] = calculate_pnl(t, ltp)

        if t["side"] == "BUY":
            if ltp <= t["sl"]:
                t["status"] = "SL HIT"
                t["exit_price"] = ltp
            elif ltp >= t["target"]:
                t["status"] = "TARGET HIT"
                t["exit_price"] = ltp
        else:
            if ltp >= t["sl"]:
                t["status"] = "SL HIT"
                t["exit_price"] = ltp
            elif ltp <= t["target"]:
                t["status"] = "TARGET HIT"
                t["exit_price"] = ltp

# ── AUTO SCAN ────────────────────────────────────────────────────────────
def auto_scan(interval_sec):
    if "last_scan" not in st.session_state:
        st.session_state["last_scan"] = 0

    if time.time() - st.session_state["last_scan"] > interval_sec:
        st.session_state["run_scan"] = True
        st.session_state["last_scan"] = time.time()

# ── SIDEBAR ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Settings")

    interval = st.selectbox("Auto Scan", ["OFF", "1 min", "5 min"])
    interval_map = {"OFF": 0, "1 min": 60, "5 min": 300}

    if st.button("🔍 Scan Now"):
        st.session_state["run_scan"] = True

    if st.button("🗑️ Reset"):
        st.session_state["signals"] = []
        st.session_state["trades"] = []
        st.rerun()

# ── RUN AUTO SCAN ────────────────────────────────────────────────────────
if interval_map[interval] > 0:
    auto_scan(interval_map[interval])

# ── UPDATE TRADES ────────────────────────────────────────────────────────
update_trades()

# ── SCAN ENGINE ──────────────────────────────────────────────────────────
if st.session_state.get("run_scan"):
    st.session_state["run_scan"] = False

    with st.spinner("Scanning multi-timeframe RSI..."):
        kite = st.session_state.get("kite")

        raw = safe_kite(run_rsi_scanner_multi_tf, kite)

        if raw is None:
            st.error("Kite error")
        else:
            now = datetime.now().strftime("%H:%M:%S")

            new = []
            for r in raw:
                signal = {
                    "symbol": r["symbol"],
                    "side": r["signal"],
                    "price": r["price"],
                    "rsi_5m": r["rsi_5m"],
                    "rsi_15m": r["rsi_15m"],
                    "time": now,
                }
                new.append(signal)

                # create trade
                st.session_state["trades"].append(create_trade(signal))

            st.session_state["signals"].extend(new)
            st.success(f"{len(new)} signals")

# ── UI ───────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📡 Signals", "📋 Trades"])

with tab1:
    if st.session_state["signals"]:
        st.dataframe(pd.DataFrame(st.session_state["signals"]), use_container_width=True)
    else:
        st.info("No signals")

with tab2:
    if st.session_state["trades"]:
        df = pd.DataFrame(st.session_state["trades"])

        total_pnl = df["pnl"].sum()

        st.metric("Total P&L", f"₹ {total_pnl:,.2f}")

        st.dataframe(df, use_container_width=True)
    else:
        st.info("No trades")