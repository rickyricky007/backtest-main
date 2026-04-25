"""
Backtest Lab
============
Run, compare, and optimise strategies against historical data — right from the dashboard.

Features:
    - Select strategy + parameters from the UI
    - Fetch historical data via Kite API
    - Run backtest → show equity curve, metrics, trade log
    - Walk-forward validation (train/test split)
    - Grid-search parameter optimisation
    - Compare multiple strategy runs side-by-side
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import kite_data as kd
from auth_streamlit import render_sidebar_kite_session
from backtest_engine import BacktestEngine, BacktestResult
from strategies import RSIStrategy, SMAStrategy, VWAPStrategy, ORBStrategy

# ── strategy registry ─────────────────────────────────────────────────────────
STRATEGY_MAP = {
    "RSI":          RSIStrategy,
    "SMA Crossover": SMAStrategy,
    "VWAP":         VWAPStrategy,
    "ORB":          ORBStrategy,
}

STRATEGY_PARAMS = {
    "RSI": {
        "period":     {"type": "int",   "default": 14,  "min": 2,   "max": 50,  "label": "RSI Period"},
        "oversold":   {"type": "int",   "default": 30,  "min": 10,  "max": 45,  "label": "Oversold Level"},
        "overbought": {"type": "int",   "default": 70,  "min": 55,  "max": 90,  "label": "Overbought Level"},
    },
    "SMA Crossover": {
        "fast_period": {"type": "int",  "default": 20,  "min": 5,   "max": 50,  "label": "Fast MA Period"},
        "slow_period": {"type": "int",  "default": 50,  "min": 20,  "max": 200, "label": "Slow MA Period"},
    },
    "VWAP": {
        "band_pct":   {"type": "float", "default": 0.05,"min": 0.01,"max": 0.5, "label": "Band % (0.05 = 0.05%)"},
        "min_volume": {"type": "int",   "default": 1000,"min": 100, "max": 100000,"label": "Min Volume"},
    },
    "ORB": {
        "range_minutes": {"type": "int","default": 15,  "min": 5,   "max": 60,  "label": "Range Minutes"},
        "buffer_pct":    {"type": "float","default": 0.1,"min": 0.0,"max": 1.0, "label": "Buffer % (0.1 = 0.1%)"},
    },
}

SYMBOLS = [
    "RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK",
    "SBIN", "NIFTY 50", "NIFTY BANK", "AXISBANK", "WIPRO",
    "BAJFINANCE", "MARUTI", "TATAMOTORS", "ONGC", "SUNPHARMA",
]

INTERVALS = {
    "1 minute":  "minute",
    "3 minutes": "3minute",
    "5 minutes": "5minute",
    "15 minutes":"15minute",
    "30 minutes":"30minute",
    "1 hour":    "60minute",
    "1 day":     "day",
}


# ── helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _fetch_historical(symbol: str, exchange: str, interval: str, days: int) -> pd.DataFrame:
    """Fetch OHLCV data from Kite."""
    try:
        kite    = kd.kite_client()
        to_date = datetime.now()
        fr_date = to_date - timedelta(days=days)

        # Get instrument token
        instr = kite.instruments(exchange)
        df_i  = pd.DataFrame(instr)
        match = df_i[df_i["tradingsymbol"] == symbol]
        if match.empty:
            return pd.DataFrame()
        token = int(match.iloc[0]["instrument_token"])

        data = kite.historical_data(token, fr_date, to_date, interval)
        df   = pd.DataFrame(data)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df
    except Exception as e:
        st.error(f"Data fetch error: {e}")
        return pd.DataFrame()


def _render_result(result: BacktestResult, label: str = "Backtest Result") -> None:
    st.subheader(f"📊 {label}")

    # Metrics
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total P&L",    f"₹{result.total_pnl:,.0f}",
              delta_color="normal" if result.total_pnl >= 0 else "inverse")
    m2.metric("Sharpe",       f"{result.sharpe_ratio:.2f}")
    m3.metric("Max Drawdown", f"₹{result.max_drawdown:,.0f}")
    m4.metric("Win Rate",     f"{result.win_rate:.1f}%")
    m5.metric("Profit Factor",f"{result.profit_factor:.2f}")
    m6.metric("Total Trades", result.total_trades)

    n1, n2, n3 = st.columns(3)
    n1.metric("Sortino",   f"{result.sortino_ratio:.2f}")
    n2.metric("Calmar",    f"{result.calmar_ratio:.2f}")
    n3.metric("Avg Trade", f"₹{result.avg_pnl_per_trade:,.0f}")

    # Equity curve
    if result.equity_curve:
        eq_df = pd.DataFrame(result.equity_curve, columns=["Date", "Equity"])
        eq_df["Date"] = pd.to_datetime(eq_df["Date"])
        eq_df = eq_df.set_index("Date")
        st.subheader("📈 Equity Curve")
        st.line_chart(eq_df, color=["#22c55e"])

    # Trade log
    if result.trades:
        st.subheader("📋 Trade Log")
        trade_rows = []
        for t in result.trades:
            trade_rows.append({
                "Entry Time":  t.entry_time,
                "Action":      t.action,
                "Entry Price": t.entry_price,
                "Exit Time":   t.exit_time,
                "Exit Price":  t.exit_price,
                "Qty":         t.quantity,
                "P&L":         t.pnl,
                "P&L %":       t.pnl_pct,
                "Duration":    t.duration,
                "Exit Reason": t.exit_reason,
            })
        tdf = pd.DataFrame(trade_rows)
        st.dataframe(
            tdf.style.format({
                "Entry Price": "₹{:.2f}", "Exit Price": "₹{:.2f}",
                "P&L": "₹{:,.0f}", "P&L %": "{:.2f}%",
            }).applymap(
                lambda v: "color:#22c55e" if isinstance(v, (int, float)) and v > 0
                else ("color:#ef4444" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["P&L"],
            ),
            use_container_width=True,
        )

        # Download
        csv = tdf.to_csv(index=False)
        st.download_button("⬇ Download Trade Log", csv,
                           file_name="trades.csv", mime="text/csv")


# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Backtest Lab", page_icon="🔬", layout="wide")
render_sidebar_kite_session()
st.title("🔬 Backtest Lab")

tab1, tab2, tab3 = st.tabs(["▶ Run Backtest", "🔍 Walk-Forward", "⚙️ Optimise"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: Run Backtest
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Configure & Run")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        strategy_name = st.selectbox("Strategy", list(STRATEGY_MAP.keys()))
    with c2:
        symbol   = st.selectbox("Symbol", SYMBOLS)
        exchange = st.selectbox("Exchange", ["NSE", "NFO", "BSE"])
    with c3:
        interval_label = st.selectbox("Interval", list(INTERVALS.keys()), index=6)
        interval       = INTERVALS[interval_label]
    with c4:
        days    = st.number_input("Historical days", min_value=30, max_value=1825, value=365, step=30)
        capital = st.number_input("Starting capital (₹)", min_value=10000, value=100000, step=10000)

    # Strategy parameters
    st.markdown("**Strategy Parameters**")
    params = {}
    param_defs = STRATEGY_PARAMS.get(strategy_name, {})
    if param_defs:
        pcols = st.columns(min(len(param_defs), 4))
        for i, (pname, pdef) in enumerate(param_defs.items()):
            with pcols[i % len(pcols)]:
                if pdef["type"] == "int":
                    params[pname] = st.number_input(
                        pdef["label"], min_value=pdef["min"],
                        max_value=pdef["max"], value=pdef["default"], step=1, key=f"p_{pname}"
                    )
                else:
                    params[pname] = st.number_input(
                        pdef["label"], min_value=float(pdef["min"]),
                        max_value=float(pdef["max"]), value=float(pdef["default"]),
                        step=0.01, key=f"p_{pname}"
                    )

    if st.button("▶ Run Backtest", type="primary"):
        with st.spinner(f"Fetching {days} days of {symbol} {interval_label} data..."):
            df = _fetch_historical(symbol, exchange, interval, days)

        if df.empty:
            st.error("No historical data found. Check symbol/exchange/interval and Kite connection.")
        else:
            st.success(f"Loaded {len(df):,} candles ({df.index[0].date()} → {df.index[-1].date()})")
            with st.spinner("Running backtest..."):
                engine = BacktestEngine(capital=capital)
                strategy_params = {
                    "symbol": symbol, "exchange": exchange,
                    "quantity": 1, "mode": "PAPER",
                    **params,
                }
                try:
                    result = engine.run(
                        strategy_class  = STRATEGY_MAP[strategy_name],
                        strategy_params = strategy_params,
                        symbol          = symbol,
                        interval        = interval,
                        days            = days,
                    )
                    st.session_state["last_result"] = result
                    st.session_state["last_label"]  = f"{strategy_name} on {symbol} ({days}d)"
                    st.success("Backtest complete!")
                except Exception as e:
                    st.error(f"Backtest error: {e}")
                    result = None

            if result:
                _render_result(result, f"{strategy_name} — {symbol}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: Walk-Forward
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Walk-Forward Validation")
    st.caption("Splits data into train/test windows — tells you if a strategy generalises.")

    wf_c1, wf_c2, wf_c3 = st.columns(3)
    with wf_c1:
        wf_strategy   = st.selectbox("Strategy", list(STRATEGY_MAP.keys()), key="wf_strat")
        wf_symbol     = st.selectbox("Symbol", SYMBOLS, key="wf_sym")
        wf_exchange   = st.selectbox("Exchange", ["NSE", "NFO", "BSE"], key="wf_exc")
    with wf_c2:
        wf_interval_l = st.selectbox("Interval", list(INTERVALS.keys()), index=6, key="wf_int")
        wf_interval   = INTERVALS[wf_interval_l]
        wf_days       = st.number_input("Total days", 180, 1825, 730, key="wf_days")
    with wf_c3:
        wf_train      = st.number_input("Train window (days)", 60, 365, 180, key="wf_train")
        wf_test       = st.number_input("Test window (days)",  20, 180,  60, key="wf_test")
        wf_capital    = st.number_input("Capital (₹)", 10000, 10000000, 100000, key="wf_cap")

    # Default params for WF
    wf_params = {}
    wf_param_defs = STRATEGY_PARAMS.get(wf_strategy, {})
    if wf_param_defs:
        wpcols = st.columns(min(len(wf_param_defs), 4))
        for i, (pname, pdef) in enumerate(wf_param_defs.items()):
            with wpcols[i % len(wpcols)]:
                if pdef["type"] == "int":
                    wf_params[pname] = st.number_input(
                        pdef["label"], min_value=pdef["min"], max_value=pdef["max"],
                        value=pdef["default"], step=1, key=f"wf_{pname}"
                    )
                else:
                    wf_params[pname] = st.number_input(
                        pdef["label"], min_value=float(pdef["min"]), max_value=float(pdef["max"]),
                        value=float(pdef["default"]), step=0.01, key=f"wf_{pname}"
                    )

    if st.button("▶ Run Walk-Forward", type="primary"):
        with st.spinner("Fetching data..."):
            wf_df = _fetch_historical(wf_symbol, wf_exchange, wf_interval, wf_days)

        if wf_df.empty:
            st.error("No data found.")
        else:
            with st.spinner(f"Running walk-forward ({wf_train}d train / {wf_test}d test)..."):
                engine = BacktestEngine(capital=wf_capital)
                sp     = {"symbol": wf_symbol, "exchange": wf_exchange,
                          "quantity": 1, "mode": "PAPER", **wf_params}
                try:
                    windows = engine.walk_forward(
                        strategy_class  = STRATEGY_MAP[wf_strategy],
                        strategy_params = sp,
                        symbol          = wf_symbol,
                        interval        = wf_interval,
                        days            = wf_days,
                        train_days      = wf_train,
                        test_days       = wf_test,
                    )
                    if not windows:
                        st.warning("No walk-forward windows generated — try increasing total days.")
                    else:
                        st.success(f"{len(windows)} walk-forward windows completed")
                        summary_rows = []
                        for i, (train_r, test_r) in enumerate(windows):
                            summary_rows.append({
                                "Window":         i + 1,
                                "Train P&L":      train_r.total_pnl,
                                "Test P&L":       test_r.total_pnl,
                                "Train Sharpe":   train_r.sharpe_ratio,
                                "Test Sharpe":    test_r.sharpe_ratio,
                                "Train Win%":     train_r.win_rate,
                                "Test Win%":      test_r.win_rate,
                                "Train Trades":   train_r.total_trades,
                                "Test Trades":    test_r.total_trades,
                            })
                        wf_summary = pd.DataFrame(summary_rows)
                        st.dataframe(
                            wf_summary.style.format({
                                "Train P&L": "₹{:,.0f}", "Test P&L": "₹{:,.0f}",
                                "Train Sharpe": "{:.2f}", "Test Sharpe": "{:.2f}",
                                "Train Win%": "{:.1f}%", "Test Win%": "{:.1f}%",
                            }),
                            use_container_width=True,
                        )
                        total_test_pnl = sum(r[1].total_pnl for r in windows)
                        avg_test_sharpe = sum(r[1].sharpe_ratio for r in windows) / len(windows)
                        st.metric("Aggregate Test P&L",   f"₹{total_test_pnl:,.0f}")
                        st.metric("Avg Test Sharpe",      f"{avg_test_sharpe:.2f}")
                        if total_test_pnl > 0 and avg_test_sharpe > 0.5:
                            st.success("✅ Strategy shows consistent out-of-sample performance")
                        elif total_test_pnl > 0:
                            st.warning("⚠️ Profitable but low Sharpe — check consistency")
                        else:
                            st.error("❌ Strategy underperforms out-of-sample — likely overfitted")
                except Exception as e:
                    st.error(f"Walk-forward error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: Optimise
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Parameter Optimisation (Grid Search)")
    st.caption("Finds the best parameter combination — always validate on walk-forward after!")

    op_c1, op_c2, op_c3 = st.columns(3)
    with op_c1:
        op_strategy = st.selectbox("Strategy", list(STRATEGY_MAP.keys()), key="op_strat")
        op_symbol   = st.selectbox("Symbol", SYMBOLS, key="op_sym")
        op_exchange = st.selectbox("Exchange", ["NSE", "NFO", "BSE"], key="op_exc")
    with op_c2:
        op_int_l    = st.selectbox("Interval", list(INTERVALS.keys()), index=6, key="op_int")
        op_interval = INTERVALS[op_int_l]
        op_days     = st.number_input("Historical days", 180, 1825, 365, key="op_days")
        op_capital  = st.number_input("Capital (₹)", 10000, 10000000, 100000, key="op_cap")
    with op_c3:
        op_metric = st.selectbox("Optimise for", ["sharpe_ratio", "total_pnl", "win_rate", "sortino_ratio"])
        st.caption("⚠️ Optimising for P&L alone → overfitting. Prefer Sharpe.")

    # Grid range inputs
    st.markdown("**Parameter Grid**")
    op_param_defs = STRATEGY_PARAMS.get(op_strategy, {})
    param_grids: dict[str, list] = {}

    if op_param_defs:
        for pname, pdef in op_param_defs.items():
            gc1, gc2, gc3 = st.columns(3)
            with gc1:
                if pdef["type"] == "int":
                    p_min = st.number_input(f"{pdef['label']} min", value=pdef["min"],
                                            step=1, key=f"opt_min_{pname}")
                else:
                    p_min = st.number_input(f"{pdef['label']} min", value=float(pdef["min"]),
                                            step=0.05, key=f"opt_min_{pname}")
            with gc2:
                if pdef["type"] == "int":
                    p_max = st.number_input(f"{pdef['label']} max", value=pdef["max"] // 2,
                                            step=1, key=f"opt_max_{pname}")
                else:
                    p_max = st.number_input(f"{pdef['label']} max", value=float(pdef["default"]) * 2,
                                            step=0.05, key=f"opt_max_{pname}")
            with gc3:
                if pdef["type"] == "int":
                    p_step = st.number_input(f"{pdef['label']} step", value=max(1, (pdef["max"] - pdef["min"]) // 5),
                                             step=1, min_value=1, key=f"opt_step_{pname}")
                    param_grids[pname] = list(range(int(p_min), int(p_max) + 1, int(p_step)))
                else:
                    p_step = st.number_input(f"{pdef['label']} step", value=float(pdef["default"]) / 5,
                                             step=0.01, min_value=0.01, key=f"opt_step_{pname}")
                    vals = []
                    v = p_min
                    while v <= p_max:
                        vals.append(round(v, 4))
                        v += p_step
                    param_grids[pname] = vals

    total_combinations = 1
    for vals in param_grids.values():
        total_combinations *= max(len(vals), 1)
    st.info(f"Grid size: **{total_combinations} combinations** to test")

    if total_combinations > 200:
        st.warning("⚠️ Large grid — may take a while. Reduce ranges or increase step size.")

    if st.button("⚙️ Run Optimisation", type="primary"):
        with st.spinner("Fetching data..."):
            op_df = _fetch_historical(op_symbol, op_exchange, op_interval, op_days)

        if op_df.empty:
            st.error("No data found.")
        else:
            with st.spinner(f"Running {total_combinations} backtests..."):
                engine = BacktestEngine(capital=op_capital)
                base_params = {"symbol": op_symbol, "exchange": op_exchange,
                               "quantity": 1, "mode": "PAPER"}
                try:
                    results = engine.optimize(
                        strategy_class  = STRATEGY_MAP[op_strategy],
                        base_params     = base_params,
                        param_grid      = param_grids,
                        symbol          = op_symbol,
                        interval        = op_interval,
                        days            = op_days,
                        metric          = op_metric,
                    )
                    if not results:
                        st.warning("No valid results — check parameters.")
                    else:
                        st.success(f"Optimisation complete — {len(results)} results")
                        rows = []
                        for params_combo, res in results[:20]:  # top 20
                            row = {**params_combo,
                                   "P&L": res.total_pnl,
                                   "Sharpe": res.sharpe_ratio,
                                   "Sortino": res.sortino_ratio,
                                   "Win%": res.win_rate,
                                   "Profit Factor": res.profit_factor,
                                   "Max DD": res.max_drawdown,
                                   "Trades": res.total_trades}
                            rows.append(row)
                        opt_df_display = pd.DataFrame(rows)
                        st.dataframe(
                            opt_df_display.style.format({
                                "P&L": "₹{:,.0f}", "Sharpe": "{:.2f}",
                                "Sortino": "{:.2f}", "Win%": "{:.1f}%",
                                "Profit Factor": "{:.2f}", "Max DD": "₹{:,.0f}",
                            }).background_gradient(subset=["Sharpe"], cmap="RdYlGn"),
                            use_container_width=True,
                        )
                        best_params, best_result = results[0]
                        st.markdown("### 🏆 Best Parameters")
                        bp_cols = st.columns(len(best_params))
                        for col, (k, v) in zip(bp_cols, best_params.items()):
                            col.metric(k, v)

                        # ── Overfitting guard ─────────────────────────────────
                        st.divider()
                        st.error(
                            "⚠️ **STOP — Read this before going LIVE**\n\n"
                            "Optimisation finds parameters that worked **best on past data**. "
                            "This does NOT mean they will work in the future. "
                            "A strategy optimised on the same data it's tested on is almost always **overfitted** — "
                            "it looks amazing on paper but loses money live.\n\n"
                            "**You must validate on walk-forward before trusting these parameters.**"
                        )
                        st.markdown("#### ✅ Next Step — Walk-Forward Validation")
                        st.info(
                            "Go to the **Walk-Forward tab**, enter the same symbol and these best parameters, "
                            "and check if the strategy is profitable on data it has **never seen before**.\n\n"
                            "Rule of thumb:\n"
                            "- Test P&L positive in **≥ 60%** of windows → strategy is real\n"
                            "- Test P&L positive in **< 50%** of windows → overfitted, don't use"
                        )

                        # Store best params in session so user can quickly jump to walk-forward
                        st.session_state["opt_best_params"]    = best_params
                        st.session_state["opt_best_strategy"]  = op_strategy
                        st.session_state["opt_best_symbol"]    = op_symbol

                        wf_confirm = st.checkbox(
                            "✅ I understand — I will run walk-forward before going LIVE",
                            key="wf_confirm"
                        )
                        if wf_confirm:
                            st.success(
                                "Good. Switch to the **Walk-Forward tab** now and validate these parameters. "
                                "Only deploy live after it passes."
                            )
                            _render_result(best_result, f"Best: {op_strategy} on {op_symbol}")
                        else:
                            st.warning(
                                "Equity curve hidden until you confirm you understand the overfitting risk. "
                                "Check the box above."
                            )
                except Exception as e:
                    st.error(f"Optimisation error: {e}")
