"""
Light Trades — Strategy L1 config (NIFTY RSI options)
=====================================================
DB-backed parameters (`app_settings`) + master enable switch. The strategy
engine must be running; turn **Enable Light L1** on to let the strategy tick.
"""

from __future__ import annotations

import math
from dataclasses import asdict

import pandas as pd
import streamlit as st

import auth_streamlit as auth
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest_engine import BacktestResult
from light_l1_backtest import LIGHT_L1_PRESETS, run_light_l1_backtest
from light_fill_quality import light_l1_last_order
from light_strategy_config import (
    LightL1DayState,
    LightNiftyRSIConfig,
    default_config,
    delete_named_profile,
    is_light_l1_enabled,
    list_named_profile_names,
    load_config,
    load_named_profiles,
    load_day_state,
    save_config,
    save_day_state,
    save_named_profile,
    set_light_l1_enabled,
)


def _profit_factor_label(v: float) -> str:
    if math.isinf(v) or v > 1e9:
        return "∞"
    return f"{v:.2f}"


def _render_light_l1_backtest(result: BacktestResult) -> None:
    st.subheader("Results")
    if isinstance(result.params, dict) and result.params.get("mode") == "no_data":
        st.warning("No OHLCV returned — check Kite token / Breeze session and try fewer days.")
        return

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total P&L", f"₹{result.total_pnl:,.0f}")
    m2.metric("Win rate", f"{result.win_rate:.1f}%")
    m3.metric("Max drawdown", f"₹{result.max_drawdown:,.0f}")
    m4.metric("Profit factor", _profit_factor_label(result.profit_factor))
    m5.metric("Trades", result.total_trades)
    m6.metric("Sharpe (approx.)", f"{result.sharpe_ratio:.2f}")

    p1, p2 = st.columns(2)
    p1.metric("Avg win", f"₹{result.avg_win:,.0f}")
    p2.metric("Avg loss", f"₹{result.avg_loss:,.0f}")
    st.caption(f"Window: **{result.start_date}** → **{result.end_date}** · notional capital ₹{result.capital:,.0f}")

    ec = result.equity_curve
    if ec is not None and hasattr(ec, "empty") and not ec.empty:
        st.subheader("Equity curve (simulated)")
        st.line_chart(ec)

    if result.trades:
        st.subheader("Trade log")
        st.dataframe(result.trades_df(), width="stretch")
    else:
        st.info("No trades in this window — widen days or relax presets/thresholds.")


st.set_page_config(page_title="Light Trades", page_icon="🪶", layout="wide")
auth.render_sidebar_kite_session()

IST = ZoneInfo("Asia/Kolkata")
today = datetime.now(IST).strftime("%Y-%m-%d")

st.title("🪶 Light Trades — L1 NIFTY RSI")
st.caption("Small-capital, single-indicator options. Config is stored in the database; no code deploy to change thresholds.")

cfg = load_config(force=True)
day_st = load_day_state(today)

if cfg.mode == "LIVE":
    st.error(
        "**LIVE trading mode** — orders use real broker routing when the strategy engine runs with this config. "
        "Double-check caps, **disable Light L1** when flat, and prefer **`python scripts/check_light_ready.py`** before the session."
    )

try:
    last_ord = light_l1_last_order()
except Exception:
    last_ord = None

st.markdown("### Mission control")
mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
mc1.metric("Mode", cfg.mode)
mc2.metric("Engine", "ON" if is_light_l1_enabled() else "OFF")
mc3.metric("Trades today", day_st.trades_today)
mc4.metric("Halted", "yes" if day_st.halted else "no")
mc5.metric("Consec. losses", day_st.consecutive_losses)
last_ts = "—"
last_detail = ""
if last_ord:
    last_ts = str(last_ord.get("timestamp") or "")[:19] or "—"
    sym = last_ord.get("symbol") or ""
    act = last_ord.get("action") or ""
    om = last_ord.get("mode") or ""
    last_detail = f"`{sym}` · **{act}** · {om}"
mc6.metric("Last order (time)", last_ts)
if last_detail:
    st.caption(f"Last order detail: {last_detail}")

st.caption(
    f"**Caps (saved config):** ≤ **{cfg.max_trades_per_day}** trades/day · **{cfg.lot_size}** lot(s) · "
    f"entry window **{cfg.entry_window_start}**–**{cfg.entry_window_end}** · "
    f"consecutive-loss halt after **{cfg.max_consecutive_losses}**"
)
st.caption("CLI check: `make status` or `python scripts/check_light_ready.py` from **`ricky_1/`**")

# ── Master switch ─────────────────────────────────────────────────────────────
on = st.toggle(
    "Enable Light L1 in strategy engine",
    value=is_light_l1_enabled(),
    help="When off, the engine skips this strategy even if it is registered.",
)
if on != is_light_l1_enabled():
    set_light_l1_enabled(on)
    st.rerun()

cfg = load_config(force=True)

if st.button("Reset daily halt / counters (today only)", help="Clears halted flag and counters for the current session date"):
    save_day_state(LightL1DayState(day=today, trades_today=0, consecutive_losses=0, halted=False))
    st.success("Daily state reset.")
    st.rerun()

st.divider()

st.subheader("Parameters")

if st.button("Restore default parameters"):
    save_config(default_config())
    st.success("Defaults restored.")
    st.rerun()

with st.form("light_l1_form"):
    st.markdown("**Rule toggles** — enable whole rule *groups* (cleaner than one switch per number). When off, that filter or exit type is skipped; numeric fields are still stored.")
    rt1, rt2 = st.columns(2)
    with rt1:
        use_entry_window = st.checkbox(
            "Entry time window",
            value=bool(getattr(cfg, "use_entry_window", True)),
            help="Off = allow new entries any time of session (still subject to max trades/day).",
        )
        use_otm_distance_filter = st.checkbox(
            "OTM distance filter",
            value=bool(getattr(cfg, "use_otm_distance_filter", True)),
            help="Off = consider all strikes on nearest weekly expiry (nearest strike to spot first).",
        )
        use_premium_band = st.checkbox(
            "Premium band (min–max ₹)",
            value=bool(getattr(cfg, "use_premium_band", True)),
            help="Off = first option with a usable quote (nearest strike ordering).",
        )
    with rt2:
        use_exit_eod = st.checkbox("Exit: EOD square-off", value=bool(getattr(cfg, "use_exit_eod", True)))
        use_exit_time_stop = st.checkbox("Exit: time stop", value=bool(getattr(cfg, "use_exit_time_stop", True)))
        use_exit_profit_target = st.checkbox("Exit: profit target %", value=bool(getattr(cfg, "use_exit_profit_target", True)))
        use_exit_stop_loss = st.checkbox("Exit: stop loss %", value=bool(getattr(cfg, "use_exit_stop_loss", True)))
        use_exit_rsi = st.checkbox("Exit: RSI levels", value=bool(getattr(cfg, "use_exit_rsi", True)))
    st.caption(
        "Backtest sim honours entry window + exit toggles; it does not replay chain selection — OTM/premium toggles affect **live** contract pick only."
    )
    st.divider()

    col_a, col_b = st.columns(2)

    with col_a:
        rsi_period = st.number_input("RSI period", min_value=5, max_value=30, value=int(cfg.rsi_period))
        rsi_buy_ce_below = st.number_input("Buy CE when RSI crosses below", min_value=1.0, max_value=100.0, value=float(cfg.rsi_buy_ce_below))
        rsi_buy_pe_above = st.number_input("Buy PE when RSI crosses above", min_value=1.0, max_value=100.0, value=float(cfg.rsi_buy_pe_above))
        rsi_exit_ce_above = st.number_input("Exit CE when RSI above", min_value=1.0, max_value=100.0, value=float(cfg.rsi_exit_ce_above))
        rsi_exit_pe_below = st.number_input("Exit PE when RSI below", min_value=1.0, max_value=100.0, value=float(cfg.rsi_exit_pe_below))
        min_premium = st.number_input("Min premium ₹", min_value=5.0, max_value=500.0, value=float(cfg.min_premium))
        max_premium = st.number_input("Max premium ₹", min_value=5.0, max_value=500.0, value=float(cfg.max_premium))
        otm_min = st.number_input("OTM distance min (points)", min_value=50.0, max_value=1000.0, value=float(cfg.otm_distance_min))
        otm_max = st.number_input("OTM distance max (points)", min_value=50.0, max_value=1000.0, value=float(cfg.otm_distance_max))

    with col_b:
        profit_target_pct = st.number_input("Profit target % on premium", min_value=5.0, max_value=300.0, value=float(cfg.profit_target_pct))
        stop_loss_pct = st.number_input("Stop loss % on premium", min_value=5.0, max_value=90.0, value=float(cfg.stop_loss_pct))
        time_stop_min = st.number_input("Time stop (minutes)", min_value=5, max_value=360, value=int(cfg.time_stop_min))
        eod_squareoff_time = st.text_input("EOD square-off (HH:MM)", value=cfg.eod_squareoff_time)
        max_trades = st.number_input("Max trades / day", min_value=1, max_value=10, value=int(cfg.max_trades_per_day))
        max_cons = st.number_input("Max consecutive losses (halt)", min_value=1, max_value=5, value=int(cfg.max_consecutive_losses))
        entry_start = st.text_input("Entry window start", value=cfg.entry_window_start)
        entry_end = st.text_input("Entry window end", value=cfg.entry_window_end)
        lot_size = st.number_input("Lots per trade", min_value=1, max_value=5, value=int(cfg.lot_size))
        mode = st.selectbox("Paper / Live", ["PAPER", "LIVE"], index=0 if cfg.mode == "PAPER" else 1)

    submitted = st.form_submit_button("Save configuration")

if submitted:
    new_cfg = LightNiftyRSIConfig(
        rsi_period=int(rsi_period),
        rsi_buy_ce_below=float(rsi_buy_ce_below),
        rsi_buy_pe_above=float(rsi_buy_pe_above),
        rsi_exit_ce_above=float(rsi_exit_ce_above),
        rsi_exit_pe_below=float(rsi_exit_pe_below),
        min_premium=float(min_premium),
        max_premium=float(max_premium),
        otm_distance_min=float(otm_min),
        otm_distance_max=float(otm_max),
        profit_target_pct=float(profit_target_pct),
        stop_loss_pct=float(stop_loss_pct),
        time_stop_min=int(time_stop_min),
        eod_squareoff_time=str(eod_squareoff_time).strip(),
        max_trades_per_day=int(max_trades),
        max_consecutive_losses=int(max_cons),
        entry_window_start=str(entry_start).strip(),
        entry_window_end=str(entry_end).strip(),
        lot_size=int(lot_size),
        mode=str(mode).upper(),
        use_entry_window=bool(use_entry_window),
        use_otm_distance_filter=bool(use_otm_distance_filter),
        use_premium_band=bool(use_premium_band),
        use_exit_eod=bool(use_exit_eod),
        use_exit_time_stop=bool(use_exit_time_stop),
        use_exit_profit_target=bool(use_exit_profit_target),
        use_exit_stop_loss=bool(use_exit_stop_loss),
        use_exit_rsi=bool(use_exit_rsi),
    )
    any_exit = (
        new_cfg.use_exit_eod
        or new_cfg.use_exit_time_stop
        or new_cfg.use_exit_profit_target
        or new_cfg.use_exit_stop_loss
        or new_cfg.use_exit_rsi
    )
    if new_cfg.min_premium > new_cfg.max_premium:
        st.error("Min premium cannot exceed max premium.")
    elif new_cfg.otm_distance_min > new_cfg.otm_distance_max:
        st.error("OTM min cannot exceed OTM max.")
    elif not any_exit:
        st.error("Enable at least one exit rule (EOD, time stop, profit target, stop loss, or RSI).")
    else:
        save_config(new_cfg)
        st.success("Saved. Cached config refreshes within ~30s in the engine (or restart engine for immediate pick-up).")
        st.rerun()

st.divider()

# ── Named profiles (optional, DB) ────────────────────────────────────────────
with st.expander("📌 Named profiles (optional)", expanded=False):
    st.caption(
        "Save and reload full **Light L1** configs under custom names (stored in **`light_l1_profiles`**). "
        "Use after **Save configuration** if you changed the form."
    )
    prof_names = list_named_profile_names()
    pa, pb = st.columns(2)
    with pa:
        pick_prof = st.selectbox("Load profile", ["—"] + prof_names, key="l1_prof_load")
    with pb:
        if st.button("Apply selected profile", type="primary", key="l1_prof_apply"):
            if pick_prof != "—":
                raw_p = load_named_profiles().get(pick_prof)
                if raw_p:
                    save_config(LightNiftyRSIConfig.from_dict(raw_p))
                    st.success(f"Applied profile **{pick_prof}**.")
                    st.rerun()
                else:
                    st.error("Profile missing.")
    new_prof_name = st.text_input("New profile name (save current saved config)", placeholder="e.g. MorningAggro", key="l1_prof_new")
    if st.button("Save **current DB config** as named profile", key="l1_prof_save"):
        name = (new_prof_name or "").strip()
        if not name:
            st.error("Enter a profile name.")
        else:
            try:
                save_named_profile(name, load_config(force=True))
                st.success(f"Saved profile **{name}**.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    pdel = st.selectbox("Delete profile", ["—"] + prof_names, key="l1_prof_del")
    if st.button("Delete selected profile", key="l1_prof_del_btn"):
        if pdel != "—":
            delete_named_profile(pdel)
            st.success(f"Removed **{pdel}**.")
            st.rerun()

st.divider()

# ── ROADMAP2 Phase 2 — offline backtest (UI) ──────────────────────────────────
with st.expander("📊 Phase 2 — Offline backtest (simulated options)", expanded=False):
    st.markdown(
        "**Data:** NIFTY 50 · **5-minute** bars via `data_manager` (Breeze first, else Kite). "
        "**Premiums:** simulated with a simple delta vs spot — compare presets & regimes only; "
        "not a forecast of live option fills."
    )
    src = st.radio(
        "Config source",
        ["Named preset", "Snapshot: current saved DB config"],
        horizontal=True,
        key="l1_bt_src",
    )
    preset_name = None
    if src == "Named preset":
        preset_name = st.selectbox(
            "Preset",
            list(LIGHT_L1_PRESETS.keys()),
            key="l1_bt_preset",
        )

    days_bt = st.slider(
        "Calendar days of history",
        min_value=7,
        max_value=180,
        value=7,
        step=1,
        help="Use **7** for a quick sanity check (~minutes fetch). Increase toward **180** for Phase 2 — allow a few minutes.",
        key="l1_bt_days",
    )
    capital_bt = st.number_input(
        "Notional capital ₹ (metrics baseline)",
        min_value=10_000.0,
        max_value=10_000_000.0,
        value=100_000.0,
        step=10_000.0,
        key="l1_bt_capital",
    )

    col_run, col_clr = st.columns(2)
    with col_run:
        run_bt = st.button("Run backtest", type="primary", key="l1_bt_run")
    with col_clr:
        if st.button("Clear backtest results", key="l1_bt_clear"):
            st.session_state.pop("l1_bt_res", None)
            st.session_state.pop("l1_bt_err", None)
            st.rerun()

    if run_bt:
        try:
            if src == "Named preset" and preset_name is not None:
                bt_cfg = LIGHT_L1_PRESETS[preset_name]
            else:
                bt_cfg = LightNiftyRSIConfig.from_dict(asdict(cfg))

            with st.spinner("Fetching NIFTY 50 (5m) and running simulation…"):
                out = run_light_l1_backtest(
                    bt_cfg,
                    days=int(days_bt),
                    capital=float(capital_bt),
                )
            st.session_state["l1_bt_res"] = out
            st.session_state.pop("l1_bt_err", None)
        except Exception as e:
            st.session_state["l1_bt_err"] = str(e)
            st.session_state.pop("l1_bt_res", None)

    if st.session_state.get("l1_bt_err"):
        st.error(f"Backtest failed: {st.session_state['l1_bt_err']}")

    if st.session_state.get("l1_bt_res") is not None:
        _render_light_l1_backtest(st.session_state["l1_bt_res"])

# ── Phase 2 — fills vs sim assumptions (engine_orders) ───────────────────────
with st.expander("📒 Phase 2 — Fills vs assumptions (slippage / IV)", expanded=False):
    st.caption(
        "**Signal ₹** = option LTP when the strategy fired · **Fill ₹** = paper fill after modeled spread/slip. "
        "**Mid premium (sim)** = `(min+max premium)/2` from saved config — same idea as the offline backtest. "
        "**IV** is filled when Kite’s quote exposes it."
    )
    try:
        from light_fill_quality import light_l1_fill_rows

        fill_rows = light_l1_fill_rows(200)
        if not fill_rows:
            st.info(
                "No **Light_NIFTY_RSI** rows in `engine_orders` yet — enable Light L1 and run paper trades."
            )
        else:
            df_fill = pd.DataFrame(fill_rows)
            df_show = df_fill.rename(
                columns={
                    "timestamp": "Time",
                    "symbol": "Symbol",
                    "action": "Action",
                    "mode": "Mode",
                    "signal_inr": "Signal ₹",
                    "fill_inr": "Fill ₹",
                    "slip_inr": "Slip ₹",
                    "slip_pct": "Slip %",
                    "mid_premium_sim_inr": "Mid prem (sim) ₹",
                    "iv_quote": "IV",
                }
            )
            st.dataframe(df_show, width="stretch", hide_index=True)
    except Exception as ex:
        st.warning(f"Could not load order history: {ex}")

st.divider()
st.markdown(
    "### Notes\n"
    "- Engine watches **NIFTY 50** ticks; orders use **weekly NIFTY options** on **NFO**.\n"
    "- Exits use live **quotes** for the option leg (not the index tick alone).\n"
    "- If no strike matches premium + OTM filters, the signal is skipped.\n"
    "- Pre-open: from **`ricky_1/`** run **`make status`** or **`python scripts/check_light_ready.py`**.\n"
)
