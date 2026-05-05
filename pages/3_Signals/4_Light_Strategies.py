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
    is_light_l1_trade_permission,
    list_named_profile_names,
    load_config,
    load_named_profiles,
    load_day_state,
    param_apply_on,
    save_config,
    save_day_state,
    save_named_profile,
    set_light_l1_enabled,
    set_light_l1_trade_permission,
)


# Must match `PARAM_APPLY_KEYS` in `light_strategy_config.py` (used for `param_apply` JSON keys).
L1_PARAM_APPLY_KEYS: tuple[str, ...] = (
    "rsi_period",
    "rsi_buy_ce_below",
    "rsi_buy_pe_above",
    "rsi_exit_ce_above",
    "rsi_exit_pe_below",
    "min_premium",
    "max_premium",
    "otm_points_min",
    "otm_points_max",
    "profit_target_pct",
    "stop_loss_pct",
    "time_stop_min",
    "eod_squareoff_time",
    "max_trades_per_day",
    "max_consecutive_losses",
    "lot_size",
)

PARAM_APPLY_LABELS: dict[str, str] = {
    "rsi_period": "RSI period",
    "rsi_buy_ce_below": "RSI buy CE below",
    "rsi_buy_pe_above": "RSI buy PE above",
    "rsi_exit_ce_above": "RSI exit CE above",
    "rsi_exit_pe_below": "RSI exit PE below",
    "min_premium": "Min premium ₹",
    "max_premium": "Max premium ₹",
    "otm_points_min": "OTM · min index points (from spot, OTM side)",
    "otm_points_max": "OTM · max index points (from spot, OTM side)",
    "profit_target_pct": "Profit target %",
    "stop_loss_pct": "Stop loss %",
    "time_stop_min": "Time stop (min)",
    "eod_squareoff_time": "EOD time (HH:MM)",
    "max_trades_per_day": "Max trades/day",
    "max_consecutive_losses": "Max consec. losses",
    "lot_size": "Lots / trade",
}

# Order inside “Apply each parameter” expander (section title, keys).
_APPLY_SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("RSI", ("rsi_period", "rsi_buy_ce_below", "rsi_buy_pe_above", "rsi_exit_ce_above", "rsi_exit_pe_below")),
    ("OTM — index points (from spot)", ("otm_points_min", "otm_points_max")),
    ("Premium (₹)", ("min_premium", "max_premium")),
    ("Exit / time", ("profit_target_pct", "stop_loss_pct", "time_stop_min", "eod_squareoff_time")),
    ("Risk / size", ("max_trades_per_day", "max_consecutive_losses", "lot_size")),
]


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

ew_note = (
    f"entry window **{cfg.entry_window_start}**–**{cfg.entry_window_end}**"
    + (" · ON" if cfg.use_entry_window else " · OFF")
)
xw_note = (
    f"exit window **{cfg.exit_window_start}**–**{cfg.exit_window_end}**"
    + (" · ON" if cfg.use_exit_window else " · OFF")
)
st.caption(
    f"**Caps (saved config):** ≤ **{cfg.max_trades_per_day}** trades/day · **{cfg.lot_size}** lot(s) · "
    f"{ew_note} · {xw_note} · "
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

trade_ok = st.toggle(
    "Trade permission (new BUY entries)",
    value=is_light_l1_trade_permission(),
    help="When OFF, Light L1 will not open new CE/PE positions. **EXIT** for an already-open leg still runs. "
    "Applies in both PAPER and LIVE (mode is unchanged).",
)
if trade_ok != is_light_l1_trade_permission():
    set_light_l1_trade_permission(trade_ok)
    st.rerun()

st.caption(f"**Trade permission (new BUY):** {'ON' if is_light_l1_trade_permission() else 'OFF'}")

if st.button("Reset daily halt / counters (today only)", help="Clears halted flag and counters for the current session date"):
    save_day_state(LightL1DayState(day=today, trades_today=0, consecutive_losses=0, halted=False))
    st.success("Daily state reset.")
    st.rerun()

st.divider()

ph1, ph2 = st.columns([3, 1])
with ph1:
    st.subheader("Parameters")
with ph2:
    st.markdown("")  # align button vertically with heading
    st.markdown("")
    if st.button("Restore defaults", help="Reset Light L1 numbers + per-field Apply switches to factory defaults"):
        save_config(default_config())
        st.success("Defaults restored.")
        st.rerun()

# Outside `st.form`: Streamlit disallows `st.button` inside forms — bulk Apply toggles must live here.
with st.expander("Apply each parameter value (per field)", expanded=True):
    st.caption(
        "**On** = the saved number/time below is used for that rule. **Off** = that field is ignored and a built‑in neutral value is used instead. "
        "**All on / All off** sets every checkbox in that section only (still **Save configuration** to persist). "
        "**OTM points** = index distance on the OTM side vs spot (CE: strike − spot; PE: spot − strike)."
    )
    for sec_i, (sec_title, keys) in enumerate(_APPLY_SECTIONS):
        hd, b_on, b_off = st.columns([4.2, 1, 1])
        with hd:
            st.markdown(f"**{sec_title}**")
        with b_on:
            if st.button("All on", key=f"l1_pa_sec_all_on_{sec_i}", help=f"Enable Apply for all “{sec_title}” fields"):
                for k in keys:
                    st.session_state[f"l1_pa_{k}"] = True
                st.rerun()
        with b_off:
            if st.button("All off", key=f"l1_pa_sec_all_off_{sec_i}", help=f"Disable Apply for all “{sec_title}” fields"):
                for k in keys:
                    st.session_state[f"l1_pa_{k}"] = False
                st.rerun()
        for key in keys:
            st.checkbox(
                PARAM_APPLY_LABELS.get(key, key),
                value=param_apply_on(cfg, key),
                key=f"l1_pa_{key}",
            )
        st.markdown("")

with st.form("light_l1_form"):
    st.markdown("**Time windows (IST)** — if **both** toggles are off, entries are not limited by the entry clock band and TP / time stop / RSI exits are not limited by the exit clock band (other rules unchanged). **EOD** and **stop loss** still apply when enabled.")
    tc1, tc2 = st.columns(2)
    with tc1:
        use_entry_window_w = st.checkbox(
            "Use entry time window",
            value=bool(cfg.use_entry_window),
            help="When off, new BUY signals may occur at any time (still subject to RSI, caps, trade permission, etc.).",
        )
    with tc2:
        use_exit_window_w = st.checkbox(
            "Use exit time window",
            value=bool(cfg.use_exit_window),
            help="When off, profit target, time stop, and RSI exits may trigger anytime. EOD and stop loss always run when their switches are on.",
        )
    tw1, tw2 = st.columns(2)
    with tw1:
        entry_start = st.text_input("Entry window start", value=cfg.entry_window_start)
        entry_end = st.text_input("Entry window end", value=cfg.entry_window_end)
    with tw2:
        exit_start = st.text_input("Exit window start", value=cfg.exit_window_start)
        exit_end = st.text_input("Exit window end", value=cfg.exit_window_end)

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
        st.markdown("**OTM — index points** (OTM side vs spot)")
        otm_points_min = st.number_input(
            "Min OTM points",
            min_value=0.0,
            max_value=5000.0,
            value=float(cfg.otm_points_min),
            help="CE: strike − spot; PE: spot − strike (index points).",
        )
        otm_points_max = st.number_input(
            "Max OTM points",
            min_value=0.0,
            max_value=5000.0,
            value=float(cfg.otm_points_max),
        )

    with col_b:
        profit_target_pct = st.number_input("Profit target % on premium", min_value=5.0, max_value=300.0, value=float(cfg.profit_target_pct))
        stop_loss_pct = st.number_input("Stop loss % on premium", min_value=5.0, max_value=90.0, value=float(cfg.stop_loss_pct))
        time_stop_min = st.number_input("Time stop (minutes)", min_value=5, max_value=360, value=int(cfg.time_stop_min))
        eod_squareoff_time = st.text_input("EOD square-off (HH:MM)", value=cfg.eod_squareoff_time)
        max_trades = st.number_input("Max trades / day", min_value=1, max_value=10, value=int(cfg.max_trades_per_day))
        max_cons = st.number_input("Max consecutive losses (halt)", min_value=1, max_value=5, value=int(cfg.max_consecutive_losses))
        lot_size = st.number_input("Lots per trade", min_value=1, max_value=5, value=int(cfg.lot_size))
        mode = st.selectbox("Paper / Live", ["PAPER", "LIVE"], index=0 if cfg.mode == "PAPER" else 1)

    submitted = st.form_submit_button("Save configuration")

if submitted:
    param_apply = {k: bool(st.session_state.get(f"l1_pa_{k}", True)) for k in L1_PARAM_APPLY_KEYS}
    new_cfg = LightNiftyRSIConfig(
        rsi_period=int(rsi_period),
        rsi_buy_ce_below=float(rsi_buy_ce_below),
        rsi_buy_pe_above=float(rsi_buy_pe_above),
        rsi_exit_ce_above=float(rsi_exit_ce_above),
        rsi_exit_pe_below=float(rsi_exit_pe_below),
        min_premium=float(min_premium),
        max_premium=float(max_premium),
        otm_points_min=float(otm_points_min),
        otm_points_max=float(otm_points_max),
        profit_target_pct=float(profit_target_pct),
        stop_loss_pct=float(stop_loss_pct),
        time_stop_min=int(time_stop_min),
        eod_squareoff_time=str(eod_squareoff_time).strip(),
        max_trades_per_day=int(max_trades),
        max_consecutive_losses=int(max_cons),
        entry_window_start=str(entry_start).strip(),
        entry_window_end=str(entry_end).strip(),
        exit_window_start=str(exit_start).strip(),
        exit_window_end=str(exit_end).strip(),
        lot_size=int(lot_size),
        mode=str(mode).upper(),
        use_entry_window=bool(use_entry_window_w),
        use_exit_window=bool(use_exit_window_w),
        use_otm_distance_filter=bool(cfg.use_otm_distance_filter),
        use_premium_band=bool(cfg.use_premium_band),
        use_exit_eod=bool(cfg.use_exit_eod),
        use_exit_time_stop=bool(cfg.use_exit_time_stop),
        use_exit_profit_target=bool(cfg.use_exit_profit_target),
        use_exit_stop_loss=bool(cfg.use_exit_stop_loss),
        use_exit_rsi=bool(cfg.use_exit_rsi),
        param_apply=param_apply,
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
    elif new_cfg.otm_points_min > new_cfg.otm_points_max:
        st.error("OTM points min cannot exceed OTM points max.")
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
