"""
Strategy Hub
============
One page to monitor, control, and review ALL active strategies.

Tabs:
    1. Live Signals   — current signal per strategy, live P&L
    2. Controls       — enable/disable strategies, switch PAPER/LIVE
    3. Signal History — all signals fired today
    4. Performance    — win rate, avg P&L, profit factor per strategy
"""

from __future__ import annotations

from datetime import datetime, date
from pathlib import Path

import pandas as pd
import streamlit as st

import auth_streamlit as auth
import kite_data as kd
from db import read_df

st.set_page_config(page_title="Strategy Hub", page_icon="🎯", layout="wide")
auth.render_sidebar_kite_session()

st.title("🎯 Strategy Hub")
st.caption("Monitor, control and review all active strategies in one place.")

# ── Strategy registry ─────────────────────────────────────────────────────────
# Add new strategies here — just append to this list. No new page needed.

STRATEGIES = [
    # ── Equity strategies ──────────────────────────────────────────────────
    {
        "name":        "RSI — RELIANCE",
        "type":        "RSI",
        "symbol":      "RELIANCE",
        "exchange":    "NSE",
        "mode":        "PAPER",
        "description": "RSI(14) oversold/overbought on RELIANCE",
        "params":      {"period": 14, "oversold": 30, "overbought": 70},
        "sl_pct":      2.0,
        "target_pct":  4.0,
    },
    {
        "name":        "RSI — INFY",
        "type":        "RSI",
        "symbol":      "INFY",
        "exchange":    "NSE",
        "mode":        "PAPER",
        "description": "RSI(14) oversold/overbought on INFY",
        "params":      {"period": 14, "oversold": 30, "overbought": 70},
        "sl_pct":      2.0,
        "target_pct":  4.0,
    },
    {
        "name":        "SMA — HDFCBANK",
        "type":        "SMA",
        "symbol":      "HDFCBANK",
        "exchange":    "NSE",
        "mode":        "PAPER",
        "description": "Golden/Death Cross SMA(20,50) on HDFCBANK",
        "params":      {"fast": 20, "slow": 50},
        "sl_pct":      1.5,
        "target_pct":  3.0,
    },
    {
        "name":        "VWAP — NIFTY",
        "type":        "VWAP",
        "symbol":      "NIFTY 50",
        "exchange":    "NSE",
        "mode":        "PAPER",
        "description": "VWAP crossover intraday on NIFTY 50",
        "params":      {},
        "sl_pct":      0.5,
        "target_pct":  1.0,
    },
    {
        "name":        "ORB — BANKNIFTY",
        "type":        "ORB",
        "symbol":      "NIFTY BANK",
        "exchange":    "NSE",
        "mode":        "PAPER",
        "description": "Opening Range Breakout (first 15 min) on BANKNIFTY",
        "params":      {"range_minutes": 15},
        "sl_pct":      0.5,
        "target_pct":  1.5,
    },
    # ── Options strategies ─────────────────────────────────────────────────
    {
        "name":        "Short Straddle — NIFTY",
        "type":        "SHORT_STRADDLE",
        "symbol":      "NIFTY 50",
        "exchange":    "NFO",
        "mode":        "PAPER",
        "description": "Sell ATM CE + PE — profits from low volatility / time decay",
        "params":      {},
        "sl_pct":      50.0,
        "target_pct":  30.0,
    },
    {
        "name":        "Short Strangle — NIFTY",
        "type":        "SHORT_STRANGLE",
        "symbol":      "NIFTY 50",
        "exchange":    "NFO",
        "mode":        "PAPER",
        "description": "Sell OTM CE + PE — wider breakevens than straddle",
        "params":      {},
        "sl_pct":      60.0,
        "target_pct":  40.0,
    },
    {
        "name":        "Long Straddle — BANKNIFTY",
        "type":        "LONG_STRADDLE",
        "symbol":      "NIFTY BANK",
        "exchange":    "NFO",
        "mode":        "PAPER",
        "description": "Buy ATM CE + PE — profits from big moves / high volatility",
        "params":      {},
        "sl_pct":      40.0,
        "target_pct":  80.0,
    },
    # ── Add more strategies below ──────────────────────────────────────────
    # {
    #     "name":        "RSI Bounce — TCS",
    #     "type":        "RSI",
    #     "symbol":      "TCS",
    #     "exchange":    "NSE",
    #     "mode":        "PAPER",
    #     "description": "RSI bounce from oversold on TCS",
    #     "params":      {"period": 9, "oversold": 25, "overbought": 75},
    #     "sl_pct":      2.0,
    #     "target_pct":  4.0,
    # },
]

# ── Session state — enabled strategies + mode overrides ───────────────────────
if "hub_enabled" not in st.session_state:
    st.session_state["hub_enabled"] = {s["name"]: True for s in STRATEGIES}
if "hub_mode" not in st.session_state:
    st.session_state["hub_mode"] = {s["name"]: s["mode"] for s in STRATEGIES}

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db_signals_today() -> pd.DataFrame:
    try:
        today = date.today().strftime("%Y-%m-%d")
        return read_df(
            "SELECT strategy, symbol, action, price, pnl, timestamp "
            "FROM strategy_trades WHERE DATE(timestamp) = %s ORDER BY timestamp DESC",
            (today,)
        )
    except Exception:
        return pd.DataFrame()


def _db_all_signals() -> pd.DataFrame:
    try:
        return read_df(
            "SELECT strategy, symbol, action, price, pnl, timestamp "
            "FROM strategy_trades ORDER BY timestamp DESC LIMIT 500"
        )
    except Exception:
        return pd.DataFrame()


def _ltp(symbol: str) -> float | None:
    try:
        ticker = kd.read_ticker_data()
        if ticker and symbol in ticker:
            return ticker[symbol].get("last_price")
        kite = kd.kite_client()
        return kd.get_ltp(kite, symbol)
    except Exception:
        return None


# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📡 Live Signals",
    "⚙️ Controls",
    "📋 Signal History",
    "📊 Performance",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — LIVE SIGNALS
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Active Strategies — Current Status")

    enabled_strategies = [
        s for s in STRATEGIES
        if st.session_state["hub_enabled"].get(s["name"], True)
    ]

    if not enabled_strategies:
        st.warning("No strategies enabled. Go to Controls tab to enable some.")
    else:
        # Fetch today's signals from DB
        today_df = _db_signals_today()

        rows = []
        for s in enabled_strategies:
            mode = st.session_state["hub_mode"].get(s["name"], s["mode"])

            # Last signal from today
            if not today_df.empty:
                match = today_df[today_df["strategy"].str.contains(s["type"], case=False, na=False)]
                match = match[match["symbol"] == s["symbol"]]
                last_signal = match.iloc[0]["action"] if not match.empty else "—"
                today_pnl   = match["pnl"].sum() if not match.empty else 0.0
                signal_count = len(match)
            else:
                last_signal  = "—"
                today_pnl    = 0.0
                signal_count = 0

            ltp = _ltp(s["symbol"])

            rows.append({
                "Strategy":       s["name"],
                "Symbol":         s["symbol"],
                "Type":           s["type"],
                "Mode":           mode,
                "Last Signal":    last_signal,
                "LTP":            f"₹{ltp:,.2f}" if ltp else "—",
                "Today Signals":  signal_count,
                "Today P&L":      today_pnl,
            })

        df = pd.DataFrame(rows)

        # Format P&L column as string with ₹ sign
        df["Today P&L"] = df["Today P&L"].apply(
            lambda x: f"₹{x:+,.0f}" if isinstance(x, (int, float)) else x
        )

        st.dataframe(df, width="stretch", hide_index=True)

        # Summary metrics
        total_pnl    = sum(r["Today P&L"] for r in rows)
        total_signals = sum(r["Today Signals"] for r in rows)
        live_count   = sum(1 for r in rows if r["Mode"] == "LIVE")
        paper_count  = sum(1 for r in rows if r["Mode"] == "PAPER")

        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Active Strategies", len(enabled_strategies))
        m2.metric("Signals Today",     total_signals)
        m3.metric("Today P&L",         f"₹{total_pnl:,.0f}", delta_color="normal")
        m4.metric("LIVE / PAPER",      f"{live_count} / {paper_count}")

        st.caption(f"Refreshed at {datetime.now().strftime('%H:%M:%S')}")
        if st.button("🔄 Refresh", key="refresh_live"):
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CONTROLS
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Strategy Controls")
    st.info("Changes here update the hub view only. To apply to live engine, restart strategy_engine.py.")

    # Group by type
    type_groups: dict[str, list] = {}
    for s in STRATEGIES:
        type_groups.setdefault(s["type"], []).append(s)

    for stype, group in type_groups.items():
        st.markdown(f"**{stype} Strategies**")
        cols = st.columns([3, 2, 2, 3])
        cols[0].markdown("Strategy")
        cols[1].markdown("Enabled")
        cols[2].markdown("Mode")
        cols[3].markdown("Description")

        for s in group:
            c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
            c1.markdown(s["name"])
            enabled = c2.toggle(
                "on", value=st.session_state["hub_enabled"].get(s["name"], True),
                key=f"en_{s['name']}",
                label_visibility="collapsed"
            )
            st.session_state["hub_enabled"][s["name"]] = enabled

            mode = c3.selectbox(
                "mode", ["PAPER", "LIVE"],
                index=0 if st.session_state["hub_mode"].get(s["name"], "PAPER") == "PAPER" else 1,
                key=f"mode_{s['name']}",
                label_visibility="collapsed"
            )
            st.session_state["hub_mode"][s["name"]] = mode
            c4.caption(s["description"])

        st.divider()

    # Bulk controls
    bc1, bc2 = st.columns(2)
    if bc1.button("✅ Enable All"):
        for s in STRATEGIES:
            st.session_state["hub_enabled"][s["name"]] = True
        st.rerun()
    if bc2.button("⏸️ Disable All"):
        for s in STRATEGIES:
            st.session_state["hub_enabled"][s["name"]] = False
        st.rerun()

    st.divider()
    st.markdown("**Strategy Parameters**")
    selected = st.selectbox("View params for:", [s["name"] for s in STRATEGIES])
    chosen   = next(s for s in STRATEGIES if s["name"] == selected)
    st.json({
        "type":       chosen["type"],
        "symbol":     chosen["symbol"],
        "exchange":   chosen["exchange"],
        "params":     chosen["params"],
        "sl_pct":     f"{chosen['sl_pct']}%",
        "target_pct": f"{chosen['target_pct']}%",
    })

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SIGNAL HISTORY
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Signal History")

    all_df = _db_all_signals()

    if all_df.empty:
        st.info("No signals recorded yet. Signals appear here once the strategy engine runs.")
    else:
        # Filters
        f1, f2, f3 = st.columns(3)
        strats      = ["All"] + sorted(all_df["strategy"].dropna().unique().tolist())
        actions     = ["All", "BUY", "SELL"]
        sel_strat   = f1.selectbox("Strategy", strats)
        sel_action  = f2.selectbox("Action", actions)
        search_sym  = f3.text_input("Symbol search", "")

        filtered = all_df.copy()
        if sel_strat != "All":
            filtered = filtered[filtered["strategy"] == sel_strat]
        if sel_action != "All":
            filtered = filtered[filtered["action"] == sel_action]
        if search_sym:
            filtered = filtered[filtered["symbol"].str.contains(search_sym.upper(), na=False)]

        st.dataframe(filtered, width="stretch", hide_index=True)

        # Download
        csv = filtered.to_csv(index=False)
        st.download_button(
            "⬇️ Download CSV", csv,
            file_name=f"signals_{date.today()}.csv",
            mime="text/csv"
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("Strategy Performance")

    all_df = _db_all_signals()

    if all_df.empty:
        st.info("No trade history yet. Performance metrics appear once signals are recorded.")
    else:
        all_df["pnl"] = pd.to_numeric(all_df["pnl"], errors="coerce").fillna(0)

        perf_rows = []
        for strat, grp in all_df.groupby("strategy"):
            total_trades = len(grp)
            wins         = (grp["pnl"] > 0).sum()
            losses       = (grp["pnl"] < 0).sum()
            win_rate     = round(wins / total_trades * 100, 1) if total_trades else 0
            total_pnl    = grp["pnl"].sum()
            avg_pnl      = grp["pnl"].mean()
            gross_profit = grp[grp["pnl"] > 0]["pnl"].sum()
            gross_loss   = abs(grp[grp["pnl"] < 0]["pnl"].sum())
            profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else float("inf")
            best_trade   = grp["pnl"].max()
            worst_trade  = grp["pnl"].min()

            perf_rows.append({
                "Strategy":      strat,
                "Trades":        total_trades,
                "Wins":          wins,
                "Losses":        losses,
                "Win Rate %":    win_rate,
                "Total P&L":     total_pnl,
                "Avg P&L":       round(avg_pnl, 2),
                "Profit Factor": profit_factor,
                "Best Trade":    best_trade,
                "Worst Trade":   worst_trade,
            })

        perf_df = pd.DataFrame(perf_rows).sort_values("Total P&L", ascending=False)

        def _colour(val):
            if isinstance(val, (int, float)):
                return f"color: {'green' if val >= 0 else 'red'}"
            return ""

        # Format currency columns without jinja2 dependency
        for col in ["Total P&L", "Avg P&L", "Best Trade", "Worst Trade"]:
            perf_df[col] = perf_df[col].apply(lambda x: f"₹{x:+,.0f}" if isinstance(x, (int, float)) else x)
        perf_df["Win Rate %"] = perf_df["Win Rate %"].apply(lambda x: f"{x:.1f}%" if isinstance(x, (int, float)) else x)

        st.dataframe(perf_df, width="stretch", hide_index=True)

        # Best strategy highlight
        best = perf_df.iloc[0]
        st.divider()
        st.markdown(f"**🏆 Best Strategy:** {best['Strategy']} — "
                    f"{best['Total P&L']} total P&L | "
                    f"{best['Win Rate %']} win rate | "
                    f"{best['Profit Factor']}x profit factor")
