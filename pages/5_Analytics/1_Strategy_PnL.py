"""
Strategy P&L Dashboard
=======================
Live view of all strategy performance:
    - Per-strategy P&L (realised + unrealised)
    - Equity curve chart
    - Win rate, Sharpe, Max Drawdown
    - Side-by-side strategy comparison
    - Trade log with filter/search
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import kite_data as kd
from auth_streamlit import render_sidebar_kite_session

DB_PATH = Path(__file__).parent.parent / "dashboard.sqlite"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy      TEXT    NOT NULL,
            symbol        TEXT    NOT NULL,
            action        TEXT    NOT NULL,   -- BUY / SELL / EXIT
            price         REAL,
            quantity      INTEGER,
            pnl           REAL    DEFAULT 0,
            mode          TEXT    DEFAULT 'PAPER',
            reason        TEXT,
            timestamp     TEXT    DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS engine_orders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      TEXT,
            symbol        TEXT,
            exchange      TEXT,
            action        TEXT,
            order_type    TEXT,
            quantity      INTEGER,
            price         REAL,
            trigger_price REAL,
            status        TEXT    DEFAULT 'PENDING',
            mode          TEXT    DEFAULT 'PAPER',
            strategy      TEXT,
            fill_price    REAL,
            fill_time     TEXT,
            created_at    TEXT    DEFAULT (datetime('now','localtime')),
            updated_at    TEXT
        )
    """)
    conn.commit()


def _load_trades(conn: sqlite3.Connection, days: int = 30) -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df = pd.read_sql_query(
            "SELECT * FROM strategy_trades WHERE timestamp >= ? ORDER BY timestamp DESC",
            conn, params=(since,),
        )
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception:
        return pd.DataFrame()


def _load_orders(conn: sqlite3.Connection, days: int = 30) -> pd.DataFrame:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df = pd.read_sql_query(
            "SELECT * FROM engine_orders WHERE created_at >= ? ORDER BY created_at DESC",
            conn, params=(since,),
        )
        return df
    except Exception:
        return pd.DataFrame()


def _strategy_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    g = trades.groupby("strategy").agg(
        total_trades=("id", "count"),
        total_pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"),
        wins=("pnl", lambda x: (x > 0).sum()),
        losses=("pnl", lambda x: (x < 0).sum()),
    ).reset_index()
    g["win_rate"] = (g["wins"] / g["total_trades"] * 100).round(1)
    g["profit_factor"] = g.apply(
        lambda r: r["wins"] * r["avg_pnl"] / max(abs(r["losses"] * r["avg_pnl"]), 1), axis=1
    )
    return g.sort_values("total_pnl", ascending=False)


def _equity_curve(trades: pd.DataFrame, strategy: str | None = None) -> pd.DataFrame:
    """Cumulative P&L over time."""
    if trades.empty:
        return pd.DataFrame()
    df = trades.copy()
    if strategy:
        df = df[df["strategy"] == strategy]
    if df.empty:
        return pd.DataFrame()
    df = df.sort_values("timestamp")
    df["cumulative_pnl"] = df["pnl"].cumsum()
    df["drawdown"] = df["cumulative_pnl"] - df["cumulative_pnl"].cummax()
    return df[["timestamp", "cumulative_pnl", "drawdown", "strategy"]]


def _max_drawdown(equity: pd.DataFrame) -> float:
    if equity.empty or "drawdown" not in equity.columns:
        return 0
    return equity["drawdown"].min()


def _sharpe(trades: pd.DataFrame) -> float:
    if trades.empty or len(trades) < 2:
        return 0
    returns = trades["pnl"]
    if returns.std() == 0:
        return 0
    return round((returns.mean() / returns.std()) * (252 ** 0.5), 2)


# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Strategy P&L", page_icon="💹", layout="wide")
render_sidebar_kite_session()
st.title("💹 Strategy P&L Dashboard")

# Ensure tables exist
try:
    conn = _get_connection()
    _init_tables(conn)
except Exception as e:
    st.error(f"Database error: {e}")
    st.stop()

# Controls
ctrl1, ctrl2 = st.columns([3, 1])
with ctrl1:
    days = st.slider("Look-back period (days)", 1, 90, 30)
with ctrl2:
    mode_filter = st.selectbox("Mode", ["ALL", "PAPER", "LIVE"])

trades = _load_trades(conn, days)
orders = _load_orders(conn, days)

if mode_filter != "ALL" and not trades.empty:
    trades = trades[trades["mode"] == mode_filter]

# ── Overall metrics ───────────────────────────────────────────────────────────
st.subheader("📊 Overall Performance")

if trades.empty:
    st.info("No trades recorded yet. Run the Strategy Engine to see results here.")
    # Show sample layout
    sample_col1, sample_col2, sample_col3, sample_col4 = st.columns(4)
    sample_col1.metric("Total P&L", "₹0")
    sample_col2.metric("Total Trades", "0")
    sample_col3.metric("Win Rate", "0%")
    sample_col4.metric("Sharpe Ratio", "0")
else:
    total_pnl   = trades["pnl"].sum()
    total_trades = len(trades)
    wins        = (trades["pnl"] > 0).sum()
    win_rate    = round(wins / total_trades * 100, 1) if total_trades else 0
    sharpe      = _sharpe(trades)
    equity      = _equity_curve(trades)
    mdd         = _max_drawdown(equity)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total P&L", f"₹{total_pnl:,.0f}",
              delta_color="normal" if total_pnl >= 0 else "inverse")
    m2.metric("Total Trades", total_trades)
    m3.metric("Win Rate", f"{win_rate}%")
    m4.metric("Sharpe Ratio", sharpe)
    m5.metric("Max Drawdown", f"₹{mdd:,.0f}",
              delta_color="inverse")

    # ── Equity curve ──────────────────────────────────────────────────────────
    if not equity.empty:
        st.subheader("📈 Equity Curve")
        chart_data = equity.set_index("timestamp")[["cumulative_pnl"]]
        st.line_chart(chart_data, color=["#22c55e"])

        st.subheader("📉 Drawdown")
        dd_data = equity.set_index("timestamp")[["drawdown"]]
        st.area_chart(dd_data, color=["#ef4444"])

# ── Per-strategy breakdown ────────────────────────────────────────────────────
st.divider()
st.subheader("🧩 Strategy Breakdown")

summary = _strategy_summary(trades) if not trades.empty else pd.DataFrame()

if summary.empty:
    st.info("No strategy data yet.")
else:
    styled_summary = summary.style.format({
        "total_pnl": "₹{:,.0f}",
        "avg_pnl":   "₹{:.2f}",
        "win_rate":  "{:.1f}%",
        "profit_factor": "{:.2f}",
    }).background_gradient(subset=["total_pnl"], cmap="RdYlGn")
    st.dataframe(styled_summary, width="stretch")

    # Per-strategy equity curves
    st.subheader("📊 Per-Strategy Equity Curves")
    strategies = trades["strategy"].unique().tolist() if not trades.empty else []
    selected   = st.multiselect("Select strategies", strategies, default=strategies[:3])
    if selected:
        curve_data = {}
        for s in selected:
            eq = _equity_curve(trades, s)
            if not eq.empty:
                eq = eq.set_index("timestamp")["cumulative_pnl"].rename(s)
                curve_data[s] = eq
        if curve_data:
            combined = pd.DataFrame(curve_data)
            st.line_chart(combined)

# ── Order book ────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📋 Order Book")

if orders.empty:
    st.info("No orders in the database.")
else:
    # Status filter
    statuses = ["ALL"] + orders["status"].unique().tolist()
    status_filter = st.selectbox("Filter by status", statuses)
    display_orders = orders if status_filter == "ALL" else orders[orders["status"] == status_filter]

    def _color_status(row):
        s = row.get("status", "")
        if s == "FILLED":
            return ["background-color:#14532d"] * len(row)
        elif s in ("CANCELLED", "REJECTED"):
            return ["background-color:#7f1d1d"] * len(row)
        elif s == "PENDING":
            return ["background-color:#1e3a5f"] * len(row)
        return [""] * len(row)

    styled_orders = display_orders[
        ["order_id", "symbol", "action", "order_type", "quantity",
         "price", "status", "strategy", "fill_price", "created_at"]
    ].style.apply(_color_status, axis=1)
    st.dataframe(styled_orders, width="stretch")

# ── Trade log ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📝 Trade Log")

if not trades.empty:
    search = st.text_input("Search trades (symbol / strategy / reason)")
    filtered = trades
    if search:
        mask = (
            trades["symbol"].str.contains(search, case=False, na=False) |
            trades["strategy"].str.contains(search, case=False, na=False) |
            trades["reason"].str.contains(search, case=False, na=False)
        )
        filtered = trades[mask]

    if filtered.empty:
        st.info("No trades match your search.")
    else:
        styled_trades = (
            filtered[["timestamp", "strategy", "symbol", "action",
                       "price", "quantity", "pnl", "reason", "mode"]]
            .style.format({
                "price": "₹{:.2f}",
                "pnl": "₹{:,.0f}",
            })
            .applymap(
                lambda v: "color:#22c55e" if isinstance(v, (int, float)) and v > 0
                else ("color:#ef4444" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["pnl"]
            )
        )
        st.dataframe(styled_trades, width="stretch")

        # CSV download
        csv = filtered.to_csv(index=False)
        st.download_button(
            "⬇ Download Trade Log (CSV)",
            data=csv,
            file_name=f"trades_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
else:
    st.info("No trades to display.")
