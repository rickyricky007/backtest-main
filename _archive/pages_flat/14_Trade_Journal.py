"""
Trade Journal
=============
Personal trade log with notes, screenshots, and analytics.

Features:
    - Add manual trade entries with tags, emotion, setup type
    - View past trades with filter / sort
    - Monthly P&L heatmap
    - Win/Loss streaks, best/worst days
    - Export to CSV
"""

import sqlite3
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import streamlit as st

from auth_streamlit import render_sidebar_kite_session

DB_PATH = Path(__file__).parent.parent / "dashboard.sqlite"


# ── DB ────────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def _init(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date   TEXT    NOT NULL,
            symbol       TEXT    NOT NULL,
            direction    TEXT    NOT NULL,  -- LONG / SHORT
            entry_price  REAL,
            exit_price   REAL,
            quantity     INTEGER,
            pnl          REAL,
            setup        TEXT,   -- e.g. ORB, VWAP, Straddle
            emotion      TEXT,   -- Confident / Fearful / Greedy / Neutral
            tags         TEXT,   -- comma-separated
            notes        TEXT,
            mistakes     TEXT,
            lessons      TEXT,
            created_at   TEXT    DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def _load(conn, days=90) -> pd.DataFrame:
    since = (datetime.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        df = pd.read_sql_query(
            "SELECT * FROM trade_journal WHERE trade_date >= ? ORDER BY trade_date DESC",
            conn, params=(since,)
        )
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    except Exception:
        return pd.DataFrame()


def _insert(conn, data: dict) -> None:
    conn.execute("""
        INSERT INTO trade_journal
            (trade_date, symbol, direction, entry_price, exit_price,
             quantity, pnl, setup, emotion, tags, notes, mistakes, lessons)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["trade_date"], data["symbol"], data["direction"],
        data["entry_price"], data["exit_price"], data["quantity"],
        data["pnl"], data["setup"], data["emotion"],
        data["tags"], data["notes"], data["mistakes"], data["lessons"],
    ))
    conn.commit()


def _delete(conn, trade_id: int) -> None:
    conn.execute("DELETE FROM trade_journal WHERE id = ?", (trade_id,))
    conn.commit()


def _monthly_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["month"] = df["trade_date"].dt.strftime("%b %Y")
    df["day"]   = df["trade_date"].dt.day
    pivot = df.pivot_table(values="pnl", index="day", columns="month", aggfunc="sum")
    return pivot


# ── streaks ───────────────────────────────────────────────────────────────────

def _streaks(pnl_series: pd.Series) -> dict:
    wins = (pnl_series > 0).astype(int)
    cur_streak = max_win = max_loss = 0
    cur_win = True
    for v in wins:
        if v == 1:
            if cur_win:
                cur_streak += 1
            else:
                cur_streak = 1
                cur_win = True
            max_win = max(max_win, cur_streak)
        else:
            if not cur_win:
                cur_streak += 1
            else:
                cur_streak = 1
                cur_win = False
            max_loss = max(max_loss, cur_streak)
    return {"max_win_streak": max_win, "max_loss_streak": max_loss}


# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Trade Journal", page_icon="📔", layout="wide")
render_sidebar_kite_session()
st.title("📔 Trade Journal")

conn = _conn()
_init(conn)

tab1, tab2, tab3 = st.tabs(["📝 Add Entry", "📊 Analytics", "📋 All Trades"])

# ── Tab 1: Add Entry ──────────────────────────────────────────────────────────
with tab1:
    st.subheader("Log a Trade")
    with st.form("journal_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            trade_date   = st.date_input("Trade Date", value=date.today())
            symbol       = st.text_input("Symbol", placeholder="NIFTY / RELIANCE / etc.")
            direction    = st.selectbox("Direction", ["LONG", "SHORT"])
        with c2:
            entry_price  = st.number_input("Entry Price (₹)", min_value=0.0, step=0.5)
            exit_price   = st.number_input("Exit Price (₹)", min_value=0.0, step=0.5)
            quantity     = st.number_input("Quantity / Lots", min_value=1, step=1, value=1)
        with c3:
            setup        = st.selectbox("Setup Type", [
                "ORB", "VWAP", "RSI", "SMA Crossover",
                "Short Straddle", "Short Strangle", "Long Straddle",
                "Iron Condor", "Scalp", "Swing", "Other",
            ])
            emotion      = st.selectbox("Emotion", [
                "Confident", "Neutral", "Fearful", "Greedy",
                "Impatient", "FOMO", "Calm",
            ])
            tags         = st.text_input("Tags (comma-separated)", placeholder="trending, gap-up, news")

        # Auto-calc P&L
        if entry_price and exit_price and quantity:
            raw_pnl = (exit_price - entry_price) * quantity if direction == "LONG" \
                      else (entry_price - exit_price) * quantity
            st.info(f"Calculated P&L: **₹{raw_pnl:,.2f}**")
        else:
            raw_pnl = 0.0

        notes    = st.text_area("Notes / Analysis", placeholder="Why did you take this trade?")
        mistakes = st.text_area("Mistakes", placeholder="What went wrong?")
        lessons  = st.text_area("Lessons Learnt", placeholder="What will you do differently?")

        submitted = st.form_submit_button("💾 Save Trade", type="primary")
        if submitted:
            if not symbol:
                st.error("Symbol is required.")
            else:
                _insert(conn, {
                    "trade_date":  str(trade_date),
                    "symbol":      symbol.upper().strip(),
                    "direction":   direction,
                    "entry_price": entry_price,
                    "exit_price":  exit_price,
                    "quantity":    quantity,
                    "pnl":         raw_pnl,
                    "setup":       setup,
                    "emotion":     emotion,
                    "tags":        tags,
                    "notes":       notes,
                    "mistakes":    mistakes,
                    "lessons":     lessons,
                })
                st.success(f"✅ Trade logged! P&L: ₹{raw_pnl:,.2f}")

# ── Tab 2: Analytics ──────────────────────────────────────────────────────────
with tab2:
    days_back = st.slider("Look-back (days)", 7, 365, 90, key="journal_days")
    df = _load(conn, days_back)

    if df.empty:
        st.info("No journal entries yet. Add your first trade in the 'Add Entry' tab!")
    else:
        total_pnl  = df["pnl"].sum()
        n_trades   = len(df)
        wins       = (df["pnl"] > 0).sum()
        losses     = (df["pnl"] <= 0).sum()
        win_rate   = round(wins / n_trades * 100, 1) if n_trades else 0
        avg_win    = df[df["pnl"] > 0]["pnl"].mean() if wins else 0
        avg_loss   = abs(df[df["pnl"] < 0]["pnl"].mean()) if losses else 0
        rr_ratio   = round(avg_win / avg_loss, 2) if avg_loss else 0
        streaks    = _streaks(df["pnl"])

        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Total P&L", f"₹{total_pnl:,.0f}",
                  delta_color="normal" if total_pnl >= 0 else "inverse")
        a2.metric("Win Rate", f"{win_rate}%")
        a3.metric("Risk-Reward", f"1:{rr_ratio}")
        a4.metric("Total Trades", n_trades)

        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Avg Win", f"₹{avg_win:,.0f}")
        b2.metric("Avg Loss", f"₹{avg_loss:,.0f}")
        b3.metric("Max Win Streak", streaks["max_win_streak"])
        b4.metric("Max Loss Streak", streaks["max_loss_streak"])

        # Daily P&L
        st.subheader("📅 Daily P&L")
        daily = df.groupby(df["trade_date"].dt.date)["pnl"].sum().reset_index()
        daily.columns = ["Date", "P&L"]
        daily["Color"] = daily["P&L"].apply(lambda x: "#22c55e" if x >= 0 else "#ef4444")
        daily_chart = daily.set_index("Date")[["P&L"]]
        st.bar_chart(daily_chart)

        # Equity curve
        st.subheader("📈 Equity Curve")
        df_sorted = df.sort_values("trade_date")
        df_sorted["cumPnL"] = df_sorted["pnl"].cumsum()
        eq_chart = df_sorted.set_index("trade_date")[["cumPnL"]]
        st.line_chart(eq_chart, color=["#22c55e"])

        # Setup performance
        st.subheader("🧩 Performance by Setup")
        setup_grp = df.groupby("setup").agg(
            trades=("id", "count"),
            pnl=("pnl", "sum"),
            win_rate=("pnl", lambda x: round((x > 0).mean() * 100, 1)),
        ).reset_index().sort_values("pnl", ascending=False)
        st.dataframe(
            setup_grp.style.format({"pnl": "₹{:,.0f}", "win_rate": "{:.1f}%"}),
            use_container_width=True,
        )

        # Emotion analysis
        st.subheader("🧠 Emotion Analysis")
        emo_grp = df.groupby("emotion").agg(
            trades=("id", "count"),
            pnl=("pnl", "sum"),
            win_rate=("pnl", lambda x: round((x > 0).mean() * 100, 1)),
        ).reset_index().sort_values("pnl", ascending=False)
        st.dataframe(
            emo_grp.style.format({"pnl": "₹{:,.0f}", "win_rate": "{:.1f}%"}),
            use_container_width=True,
        )
        st.caption("💡 Track which emotions lead to your best and worst trades")

# ── Tab 3: All Trades ─────────────────────────────────────────────────────────
with tab3:
    days_all = st.slider("Look-back (days)", 7, 365, 30, key="journal_all_days")
    df_all   = _load(conn, days_all)

    if df_all.empty:
        st.info("No journal entries yet.")
    else:
        # Search
        search = st.text_input("Search (symbol, setup, tags, notes)")
        filtered = df_all
        if search:
            mask = (
                df_all["symbol"].str.contains(search, case=False, na=False) |
                df_all["setup"].str.contains(search, case=False, na=False) |
                df_all["tags"].str.contains(search, case=False, na=False) |
                df_all["notes"].str.contains(search, case=False, na=False)
            )
            filtered = df_all[mask]

        display_cols = [
            "trade_date", "symbol", "direction", "setup", "emotion",
            "entry_price", "exit_price", "quantity", "pnl", "tags"
        ]
        st.dataframe(
            filtered[display_cols].style.format({
                "entry_price": "₹{:.2f}",
                "exit_price": "₹{:.2f}",
                "pnl": "₹{:,.0f}",
            }).applymap(
                lambda v: "color:#22c55e" if isinstance(v, (int, float)) and v > 0
                else ("color:#ef4444" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["pnl"],
            ),
            use_container_width=True,
        )

        # Delete a trade
        st.divider()
        del_id = st.number_input("Delete trade by ID", min_value=1, step=1, value=1)
        if st.button("🗑 Delete Trade", type="secondary"):
            _delete(conn, del_id)
            st.success(f"Trade #{del_id} deleted.")
            st.rerun()

        # CSV export
        csv = filtered.to_csv(index=False)
        st.download_button(
            "⬇ Export Journal (CSV)",
            data=csv,
            file_name=f"journal_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
