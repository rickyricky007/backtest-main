"""
Signal Scanner — Live Multi-Symbol Confluence Dashboard
========================================================
Shows real-time scores for all F&O symbols using 10-indicator system.

Features:
- Score table for all symbols (sorted by score)
- Indicator breakdown per symbol
- BUY/SELL signals with one-click paper trade
- PAPER / LIVE mode toggle
- Auto-refresh every 5 minutes during market hours
"""

from __future__ import annotations

import time
from datetime import datetime

import streamlit as st
import pandas as pd

import auth_streamlit as auth
from fo_symbols import FO_INDICES, TOP_50_LIQUID, ALL_FO_SYMBOLS
from signal_engine import SignalEngine
from indicators import BUY_THRESHOLD, SELL_THRESHOLD, MAX_SCORE

st.set_page_config(page_title="Signal Scanner", page_icon="🎯", layout="wide")
auth.render_sidebar_kite_session()

st.title("🎯 Signal Scanner — Confluence Engine")
st.caption("10-indicator weighted scoring across all F&O symbols")

# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Scanner Settings")

    mode = st.radio(
        "Trading Mode",
        ["PAPER", "LIVE"],
        index=0,
        help="PAPER = simulate trades only. LIVE = real orders to Kite."
    )

    if mode == "LIVE":
        st.error("⚠️ LIVE mode — real orders will be placed!")

    universe = st.selectbox(
        "Symbol Universe",
        ["Indices Only", "Top 50 Liquid", "All F&O (~180)"],
        index=1,
    )

    score_filter = st.slider(
        "Show signals with |score| ≥",
        min_value=1, max_value=MAX_SCORE, value=BUY_THRESHOLD,
        help=f"BUY threshold: +{BUY_THRESHOLD} | SELL threshold: {SELL_THRESHOLD}"
    )

    auto_refresh = st.toggle("Auto Refresh (5 min)", value=False)

    st.divider()
    st.markdown(f"""
    **Scoring guide:**
    - Score ≥ **+{BUY_THRESHOLD}** → 🟢 BUY
    - Score ≤ **{SELL_THRESHOLD}** → 🔴 SELL
    - Between → ⚪ WAIT
    - Max score: **±{MAX_SCORE}**
    """)

# ── Symbol universe ───────────────────────────────────────────────────────────
universe_map = {
    "Indices Only":     list(FO_INDICES.keys()),
    "Top 50 Liquid":    list(FO_INDICES.keys()) + TOP_50_LIQUID,
    "All F&O (~180)":   ALL_FO_SYMBOLS,
}
symbols = universe_map[universe]

# ── Session state ─────────────────────────────────────────────────────────────
if "scanner_results" not in st.session_state:
    st.session_state["scanner_results"] = []
if "last_scan_time" not in st.session_state:
    st.session_state["last_scan_time"] = None
if "engine" not in st.session_state:
    st.session_state["engine"] = SignalEngine(mode=mode, symbols=symbols)

engine: SignalEngine = st.session_state["engine"]
engine.set_mode(mode)
engine.symbols = symbols

# ── Scan controls ─────────────────────────────────────────────────────────────
col_btn1, col_btn2, col_status = st.columns([1, 1, 4])

with col_btn1:
    scan_clicked = st.button("🔍 Scan Now", type="primary", width="stretch")

with col_btn2:
    execute_clicked = st.button(
        "⚡ Scan & Trade",
        width="stretch",
        help="Scan all symbols AND auto-execute signals that pass risk checks"
    )

# ── Auto refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    last = st.session_state["last_scan_time"]
    if last is None or (time.time() - last) > 300:
        scan_clicked = True

# ── Run scan ──────────────────────────────────────────────────────────────────
if scan_clicked or execute_clicked:
    with st.spinner(f"Scanning {len(symbols)} symbols..."):
        if execute_clicked:
            executed = engine.scan_and_trade()
            st.session_state["scanner_results"] = engine.scan_all()
            if executed:
                st.success(f"✅ Executed {len(executed)} signals in {mode} mode")
            else:
                st.info("No signals executed (none passed risk checks)")
        else:
            st.session_state["scanner_results"] = engine.scan_all()

    st.session_state["last_scan_time"] = time.time()

results = st.session_state["scanner_results"]

# ── Last scan info ────────────────────────────────────────────────────────────
if st.session_state["last_scan_time"]:
    age = int(time.time() - st.session_state["last_scan_time"])
    with col_status:
        st.caption(f"Last scan: {datetime.now().strftime('%H:%M:%S')} | {len(results)} symbols | Age: {age}s")

if not results:
    st.info("👆 Click **Scan Now** to start scanning all F&O symbols")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
buy_signals  = [r for r in results if r["action"] == "BUY"]
sell_signals = [r for r in results if r["action"] == "SELL"]
wait_signals = [r for r in results if r["action"] == "WAIT"]
error_count  = sum(1 for r in results if r.get("error"))

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("🟢 BUY Signals",  len(buy_signals))
m2.metric("🔴 SELL Signals", len(sell_signals))
m3.metric("⚪ WAIT",          len(wait_signals))
m4.metric("⚠️ Errors",        error_count)
m5.metric("Mode",             mode)

st.divider()

# ── Main tabs ─────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Score Table", "🔍 Signal Detail", "📈 BUY / SELL Only"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCORE TABLE
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("All Symbols — Confluence Scores")

    rows = []
    for r in results:
        if r.get("error"):
            continue

        # Indicator summary
        buy_count  = sum(1 for s in r["signals"] if s["score"] > 0)
        sell_count = sum(1 for s in r["signals"] if s["score"] < 0)

        action_emoji = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "WAIT": "⚪ WAIT"}

        rows.append({
            "Symbol":        r["symbol"],
            "Price":         f"₹{r['price']:,.2f}" if r["price"] else "—",
            "Score":         r["score"],
            "Score %":       f"{r['pct']:+.0f}%",
            "Action":        action_emoji.get(r["action"], r["action"]),
            "🟢 BUY signals":  buy_count,
            "🔴 SELL signals": sell_count,
            "Time":          r["timestamp"],
        })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True, height=500)

        # Download
        csv = pd.DataFrame(rows).to_csv(index=False)
        st.download_button(
            "⬇️ Download CSV", csv,
            file_name=f"scanner_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — INDICATOR BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Indicator Breakdown — Per Symbol")

    valid_symbols = [r["symbol"] for r in results if not r.get("error") and r["signals"]]

    if not valid_symbols:
        st.info("Run a scan first")
    else:
        selected = st.selectbox("Select symbol to inspect:", valid_symbols)
        sym_result = next((r for r in results if r["symbol"] == selected), None)

        if sym_result:
            # Header
            action = sym_result["action"]
            score  = sym_result["score"]
            price  = sym_result["price"]
            color  = {"BUY": "🟢", "SELL": "🔴", "WAIT": "⚪"}.get(action, "")

            st.markdown(
                f"### {color} {selected} — Score: **{score:+d} / {MAX_SCORE}** | "
                f"Action: **{action}** | Price: ₹{price:,.2f}"
            )

            # Progress bar
            normalized = (score + MAX_SCORE) / (2 * MAX_SCORE)
            st.progress(normalized)
            st.caption(
                f"BUY threshold: +{BUY_THRESHOLD} | "
                f"SELL threshold: {SELL_THRESHOLD} | "
                f"Current: {score:+d}"
            )

            # Indicator table
            ind_rows = []
            for s in sym_result["signals"]:
                signal_emoji = {"BUY": "🟢", "SELL": "🔴", "—": "⚪"}.get(s["signal"], "")
                ind_rows.append({
                    "Indicator":  s["indicator"],
                    "Signal":     f"{signal_emoji} {s['signal']}",
                    "Score":      f"{s['score']:+d}",
                    "Max Weight": f"±{s['weight']}",
                })

            st.dataframe(
                pd.DataFrame(ind_rows),
                width="stretch",
                hide_index=True
            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — BUY / SELL SIGNALS ONLY
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader(f"Active Signals (|score| ≥ {score_filter})")

    active = [
        r for r in results
        if r["action"] in ("BUY", "SELL")
        and abs(r["score"]) >= score_filter
        and not r.get("error")
    ]

    if not active:
        st.info(f"No signals with |score| ≥ {score_filter}. Try lowering the filter or run a new scan.")
    else:
        for r in active:
            action  = r["action"]
            symbol  = r["symbol"]
            score   = r["score"]
            price   = r["price"]
            color   = "🟢" if action == "BUY" else "🔴"

            with st.expander(
                f"{color} **{symbol}** — {action} | Score: {score:+d} | ₹{price:,.2f}",
                expanded=(len(active) <= 5)
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Score", f"{score:+d} / {MAX_SCORE}")
                c2.metric("Score %", f"{r['pct']:+.0f}%")
                c3.metric("Price", f"₹{price:,.2f}")

                # Indicator breakdown
                ind_rows = []
                for s in r["signals"]:
                    sig_emoji = {"BUY": "🟢", "SELL": "🔴", "—": "⚪"}.get(s["signal"], "")
                    ind_rows.append({
                        "Indicator": s["indicator"],
                        "Signal":    f"{sig_emoji} {s['signal']}",
                        "Score":     f"{s['score']:+d}",
                    })

                st.dataframe(
                    pd.DataFrame(ind_rows),
                    width="stretch",
                    hide_index=True
                )

                # Manual trade button
                btn_col1, btn_col2 = st.columns(2)
                if btn_col1.button(
                    f"📄 Paper {action} {symbol}",
                    key=f"paper_{symbol}",
                    type="primary" if action == "BUY" else "secondary"
                ):
                    executed = engine.scan_and_trade(symbols=[symbol])
                    if executed:
                        st.success(f"✅ Paper {action} executed for {symbol}")
                    else:
                        st.warning("Signal blocked by risk manager")

st.divider()
st.caption(
    f"Signal Scanner | Mode: {mode} | Universe: {universe} | "
    f"Threshold: BUY ≥ +{BUY_THRESHOLD} | SELL ≤ {SELL_THRESHOLD}"
)
