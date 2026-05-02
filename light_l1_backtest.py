"""
Light L1 — offline backtest (ROADMAP2 Phase 2)
===============================================
Uses **NIFTY 50** 5-minute OHLCV via `data_manager.get_historical` (Breeze → Kite).
Option **premiums are simulated**: historical option-chain bars are optional (Breeze F&O),
so we mark P&L with a directional delta vs spot moves plus TP/SL/time/EOD/RSI exits —
same rules as `strategies/light_nifty_rsi.py`, **not** a guarantee of live fills.

Safe defaults: **never writes** `light_l1_*` DB keys; runs with an in-memory `LightNiftyRSIConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from backtest_engine import BacktestResult, Trade
from data_manager import get_historical
from light_strategy_config import LightNiftyRSIConfig
from logger import get_logger

log = get_logger("light_l1_backtest")

IST = ZoneInfo("Asia/Kolkata")
INDEX_SYMBOL = "NIFTY 50"
# Contract lot size (units per lot) — adjust when exchange revises NIFTY lot.
DEFAULT_NIFTY_OPTION_LOT_UNITS = 75
# Rough ₹ change in option premium per 1 NIFTY index point (ATM-ish proxy).
DEFAULT_DELTA_RS_PER_POINT = 0.38


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = str(s).strip().split(":")
    h = int(parts[0]) if parts else 9
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _wilder_rsi(closes: list[float], period: int) -> float:
    if len(closes) < period + 1:
        return 50.0
    arr = np.array(closes[-(period * 3) :])
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _ensure_ist(ts: Any) -> datetime:
    t = pd.Timestamp(ts).to_pydatetime()
    if t.tzinfo is None:
        return t.replace(tzinfo=IST)
    return t.astimezone(IST)


def _in_entry_window(cfg: LightNiftyRSIConfig, now: datetime) -> bool:
    sh, sm = _parse_hhmm(cfg.entry_window_start)
    eh, em = _parse_hhmm(cfg.entry_window_end)
    t = now.time()
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0).time()
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0).time()
    return start <= t <= end


def _eod_exit_due(cfg: LightNiftyRSIConfig, now: datetime) -> bool:
    eh, em = _parse_hhmm(cfg.eod_squareoff_time)
    cutoff = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return now >= cutoff


def fetch_nifty_5m(days: int) -> pd.DataFrame:
    """Pull NIFTY 50 cash 5-minute candles (Breeze preferred, else Kite)."""
    df = get_historical(INDEX_SYMBOL, "NSE", "5minute", days)
    if df.empty:
        log.warning("No NIFTY 50 5m data — check Breeze session or Kite token.")
    return df


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "datetime" not in out.columns and out.index.name == "datetime":
        out = out.reset_index()
    out["datetime"] = pd.to_datetime(out["datetime"])
    out = out.sort_values("datetime").reset_index(drop=True)
    out = out[out["datetime"].dt.dayofweek < 5]
    return out


def _mark_option_premium(
    opt_type: str,
    option_price: float,
    spot: float,
    prev_spot: float,
    delta_rs_per_point: float,
) -> float:
    d_spot = spot - prev_spot
    if opt_type == "CE":
        raw = option_price + delta_rs_per_point * d_spot
    else:
        raw = option_price - delta_rs_per_point * d_spot
    return max(0.05, float(raw))


LIGHT_L1_PRESETS: dict[str, LightNiftyRSIConfig] = {
    "Current form (copy of defaults)": LightNiftyRSIConfig(),
    "Aggressive": LightNiftyRSIConfig(
        rsi_buy_ce_below=20.0,
        rsi_buy_pe_above=80.0,
        stop_loss_pct=20.0,
        profit_target_pct=40.0,
        time_stop_min=60,
    ),
    "Conservative": LightNiftyRSIConfig(
        rsi_buy_ce_below=28.0,
        rsi_buy_pe_above=72.0,
        rsi_exit_ce_above=32.0,
        rsi_exit_pe_below=68.0,
        stop_loss_pct=35.0,
        profit_target_pct=55.0,
    ),
    "Time-based (10:00–12:00 only)": LightNiftyRSIConfig(
        entry_window_start="10:00",
        entry_window_end="12:00",
    ),
    "Premium-focused (₹20–30)": LightNiftyRSIConfig(
        min_premium=20.0,
        max_premium=30.0,
        otm_distance_min=80.0,
        otm_distance_max=200.0,
    ),
    "Distance-focused (300–500 pt OTM)": LightNiftyRSIConfig(
        otm_distance_min=300.0,
        otm_distance_max=500.0,
        min_premium=15.0,
        max_premium=45.0,
    ),
}


@dataclass
class _DaySim:
    trades_today: int = 0
    consecutive_losses: int = 0
    halted: bool = False


def run_light_l1_backtest(
    cfg: LightNiftyRSIConfig,
    days: int = 180,
    capital: float = 100_000.0,
    df: pd.DataFrame | None = None,
    *,
    index_lot_units: int = DEFAULT_NIFTY_OPTION_LOT_UNITS,
    delta_rs_per_point: float = DEFAULT_DELTA_RS_PER_POINT,
) -> BacktestResult:
    """
    Simulate Light L1 on historical NIFTY 5m bars.

    Does not read or write `light_l1_*` app_settings keys.
    """
    cfg = replace(cfg, mode="PAPER")
    raw = _prepare_df(df if df is not None else fetch_nifty_5m(days))
    if raw.empty:
        return BacktestResult(
            symbol=INDEX_SYMBOL,
            strategy="Light_NIFTY_RSI (sim)",
            params={"mode": "no_data"},
            trades=[],
            equity_curve=pd.Series(dtype=float),
            capital=capital,
            start_date="—",
            end_date="—",
        )

    rsi_closes: list[float] = []
    prev_rsi: float | None = None
    open_leg: dict[str, Any] | None = None
    day_key: str | None = None
    day_st = _DaySim()

    trades: list[Trade] = []
    equity = capital
    eq_series: list[float] = []
    eq_times: list[pd.Timestamp] = []

    period = max(2, int(cfg.rsi_period))
    entry_premium_hint = (cfg.min_premium + cfg.max_premium) / 2.0

    for _, row in raw.iterrows():
        ts = row["datetime"]
        now = _ensure_ist(ts)
        d_str = now.strftime("%Y-%m-%d")

        if day_key != d_str:
            day_key = d_str
            day_st = _DaySim()

        close = float(row["close"])
        rsi_closes.append(close)
        if len(rsi_closes) > 500:
            rsi_closes.pop(0)

        if len(rsi_closes) < period + 1:
            eq_series.append(equity)
            eq_times.append(pd.Timestamp(ts))
            continue

        rsi = _wilder_rsi(rsi_closes, period)
        skip_new_entry = False

        # --- manage open leg ---
        if open_leg:
            spot = close
            prev_sp = float(open_leg["prev_spot"])
            ltp = _mark_option_premium(
                open_leg["opt_type"],
                float(open_leg["option_price"]),
                spot,
                prev_sp,
                delta_rs_per_point,
            )
            open_leg["option_price"] = ltp
            open_leg["prev_spot"] = spot

            leg = open_leg
            entry = float(leg["entry_price"])
            opt_type = leg["opt_type"]

            exit_reason: str | None = None

            if cfg.use_exit_eod and _eod_exit_due(cfg, now):
                exit_reason = "EOD square-off"
            elif cfg.use_exit_time_stop:
                elapsed_min = (now - leg["entry_time"]).total_seconds() / 60.0
                if elapsed_min >= cfg.time_stop_min:
                    exit_reason = f"Time stop ({cfg.time_stop_min} min)"
            if exit_reason is None and cfg.use_exit_profit_target:
                tp = entry * (1.0 + cfg.profit_target_pct / 100.0)
                if ltp >= tp:
                    exit_reason = f"Profit target +{cfg.profit_target_pct}%"
            if exit_reason is None and cfg.use_exit_stop_loss:
                sl = entry * (1.0 - cfg.stop_loss_pct / 100.0)
                if ltp <= sl:
                    exit_reason = f"Stop loss -{cfg.stop_loss_pct}%"
            if exit_reason is None and cfg.use_exit_rsi:
                if opt_type == "CE" and rsi > cfg.rsi_exit_ce_above:
                    exit_reason = f"RSI exit CE (RSI={rsi} > {cfg.rsi_exit_ce_above})"
                elif opt_type == "PE" and rsi < cfg.rsi_exit_pe_below:
                    exit_reason = f"RSI exit PE (RSI={rsi} < {cfg.rsi_exit_pe_below})"

            if exit_reason:
                qty = int(leg["qty"])
                pnl = (ltp - entry) * qty
                if pnl < 0:
                    day_st.consecutive_losses += 1
                    if day_st.consecutive_losses >= cfg.max_consecutive_losses:
                        day_st.halted = True
                else:
                    day_st.consecutive_losses = 0

                trades.append(
                    Trade(
                        symbol=f"SIM_{opt_type}",
                        action="BUY",
                        entry_time=leg["entry_time"],
                        entry_price=entry,
                        quantity=qty,
                        exit_time=now,
                        exit_price=ltp,
                        exit_reason=exit_reason,
                    )
                )
                equity += pnl
                open_leg = None
                skip_new_entry = True

        # --- new entries (same bar as exit: skip — live returns one signal per tick) ---
        if (
            not open_leg
            and not day_st.halted
            and not skip_new_entry
        ):
            if day_st.trades_today < cfg.max_trades_per_day and (
                not cfg.use_entry_window or _in_entry_window(cfg, now)
            ):
                prev = prev_rsi
                ce_cross = (
                    prev is not None
                    and prev >= cfg.rsi_buy_ce_below
                    and rsi < cfg.rsi_buy_ce_below
                )
                pe_cross = (
                    prev is not None
                    and prev <= cfg.rsi_buy_pe_above
                    and rsi > cfg.rsi_buy_pe_above
                )

                if ce_cross and not pe_cross:
                    qty = int(cfg.lot_size) * index_lot_units
                    ep = entry_premium_hint
                    open_leg = {
                        "opt_type": "CE",
                        "entry_price": ep,
                        "entry_time": now,
                        "qty": qty,
                        "option_price": ep,
                        "prev_spot": close,
                    }
                    day_st.trades_today += 1
                elif pe_cross and not ce_cross:
                    qty = int(cfg.lot_size) * index_lot_units
                    ep = entry_premium_hint
                    open_leg = {
                        "opt_type": "PE",
                        "entry_price": ep,
                        "entry_time": now,
                        "qty": qty,
                        "option_price": ep,
                        "prev_spot": close,
                    }
                    day_st.trades_today += 1

        prev_rsi = rsi
        eq_series.append(equity)
        eq_times.append(pd.Timestamp(ts))

    # Force-close open leg at last mark
    if open_leg and not raw.empty:
        last = raw.iloc[-1]
        now = _ensure_ist(last["datetime"])
        ltp = float(open_leg["option_price"])
        entry = float(open_leg["entry_price"])
        qty = int(open_leg["qty"])
        pnl = (ltp - entry) * qty
        trades.append(
            Trade(
                symbol=f"SIM_{open_leg['opt_type']}",
                action="BUY",
                entry_time=open_leg["entry_time"],
                entry_price=entry,
                quantity=qty,
                exit_time=now,
                exit_price=ltp,
                exit_reason="End of series",
            )
        )
        equity += pnl
        eq_series.append(equity)
        eq_times.append(pd.Timestamp(last["datetime"]))

    eq_curve = pd.Series(eq_series, index=pd.DatetimeIndex(eq_times))

    start_d = str(raw["datetime"].iloc[0])[:10]
    end_d = str(raw["datetime"].iloc[-1])[:10]

    return BacktestResult(
        symbol=INDEX_SYMBOL,
        strategy="Light_NIFTY_RSI (sim)",
        params={
            "rsi_period": cfg.rsi_period,
            "days_requested": days,
            "mode": "PAPER",
            "note": "option premiums simulated — not historical chain replay",
        },
        trades=trades,
        equity_curve=eq_curve,
        capital=capital,
        start_date=start_d,
        end_date=end_d,
    )
