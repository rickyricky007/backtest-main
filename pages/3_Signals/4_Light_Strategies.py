"""
Light Trades — Strategy L1 config (NIFTY RSI options)
=====================================================
DB-backed parameters (`app_settings`) + master enable switch. The strategy
engine must be running; turn **Enable Light L1** on to let the strategy tick.
"""

from __future__ import annotations

import streamlit as st

import auth_streamlit as auth
from datetime import datetime
from zoneinfo import ZoneInfo

from light_strategy_config import (
    LightL1DayState,
    LightNiftyRSIConfig,
    default_config,
    is_light_l1_enabled,
    load_config,
    load_day_state,
    save_config,
    save_day_state,
    set_light_l1_enabled,
)

st.set_page_config(page_title="Light Trades", page_icon="🪶", layout="wide")
auth.render_sidebar_kite_session()

IST = ZoneInfo("Asia/Kolkata")
today = datetime.now(IST).strftime("%Y-%m-%d")

st.title("🪶 Light Trades — L1 NIFTY RSI")
st.caption("Small-capital, single-indicator options. Config is stored in the database; no code deploy to change thresholds.")

# ── Master switch ─────────────────────────────────────────────────────────────
on = st.toggle("Enable Light L1 in strategy engine", value=is_light_l1_enabled(), help="When off, the engine skips this strategy even if it is registered.")
if on != is_light_l1_enabled():
    set_light_l1_enabled(on)
    st.rerun()

cfg = load_config(force=True)
day_st = load_day_state(today)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Trades today", day_st.trades_today)
c2.metric("Consecutive losses", day_st.consecutive_losses)
c3.metric("Halted (daily)", "yes" if day_st.halted else "no")
c4.metric("Mode (config)", cfg.mode)

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
    )
    if new_cfg.min_premium > new_cfg.max_premium:
        st.error("Min premium cannot exceed max premium.")
    elif new_cfg.otm_distance_min > new_cfg.otm_distance_max:
        st.error("OTM min cannot exceed OTM max.")
    else:
        save_config(new_cfg)
        st.success("Saved. Cached config refreshes within ~30s in the engine (or restart engine for immediate pick-up).")
        st.rerun()

st.divider()
st.markdown(
    "### Notes\n"
    "- Engine watches **NIFTY 50** ticks; orders use **weekly NIFTY options** on **NFO**.\n"
    "- Exits use live **quotes** for the option leg (not the index tick alone).\n"
    "- If no strike matches premium + OTM filters, the signal is skipped.\n"
)
