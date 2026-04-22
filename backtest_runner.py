"""Long-only backtests on OHLCV loaded from SQLite (next-bar open execution)."""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd


def _rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, math.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=int(window), min_periods=int(window)).mean()


def _run_sma_cross(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    fast_p = int(params.get("fast_period", 10))
    slow_p = int(params.get("slow_period", 50))
    if fast_p >= slow_p:
        raise ValueError("sma_cross requires fast_period < slow_period")
    c = df["close"].astype(float)
    fast = _sma(c, fast_p)
    slow = _sma(c, slow_p)
    bull = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    bear = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    return bull.fillna(False), bear.fillna(False)


def _run_rsi_signals(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    period = int(params.get("period", 14))
    oversold = float(params.get("oversold", 30))
    overbought = float(params.get("overbought", 70))
    rsi = _rsi_wilder(df["close"].astype(float), period)
    buy = rsi < oversold
    sell = rsi > overbought
    return buy.fillna(False), sell.fillna(False)


def _run_bollinger_signals(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    window = int(params.get("window", 20))
    num_std = float(params.get("num_std", 2.0))
    c = df["close"].astype(float)
    mid = _sma(c, window)
    std = c.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    buy = c < lower
    sell = c >= mid
    return buy.fillna(False), sell.fillna(False)


def _simulate_long_only_next_open(
    df: pd.DataFrame,
    want_buy: pd.Series,
    want_sell: pd.Series,
    initial_cash: float = 100_000.0,
) -> dict[str, Any]:
    """Buy/sell signals evaluated at bar i; execution at open of bar i+1."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n < 3:
        raise ValueError("Need at least 3 bars to backtest with next-bar execution.")

    cash = float(initial_cash)
    shares = 0.0
    position = 0  # 0 flat, 1 long
    trades: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []

    for i in range(n - 1):
        ts = str(df.at[i, "bar_ts"])
        o_next = float(df.at[i + 1, "open"])
        c = float(df.at[i, "close"])

        # mark-to-market at close
        eq = cash + shares * c
        equity.append({"bar_ts": ts, "equity": eq})

        if position == 0 and bool(want_buy.iloc[i]) and shares == 0:
            if o_next > 0 and cash > 0:
                shares = cash / o_next
                trades.append({"side": "buy", "at_bar_ts": str(df.at[i + 1, "bar_ts"]), "price": o_next, "shares": shares})
                cash = 0.0
                position = 1
        elif position == 1 and bool(want_sell.iloc[i]) and shares > 0:
            cash = shares * o_next
            trades.append({"side": "sell", "at_bar_ts": str(df.at[i + 1, "bar_ts"]), "price": o_next, "shares": shares})
            shares = 0.0
            position = 0

    # final mark
    last_c = float(df.at[n - 1, "close"])
    equity.append({"bar_ts": str(df.at[n - 1, "bar_ts"]), "equity": cash + shares * last_c})

    start_eq = float(equity[0]["equity"]) if equity else initial_cash
    end_eq = float(equity[-1]["equity"]) if equity else initial_cash
    ret_pct = ((end_eq / start_eq) - 1.0) * 100.0 if start_eq > 0 else 0.0

    rets = pd.Series([e["equity"] for e in equity]).pct_change().dropna()
    sharpe = 0.0
    if len(rets) > 2 and float(rets.std()) > 0:
        sharpe = float(rets.mean() / rets.std() * math.sqrt(252))

    peak = -math.inf
    max_dd = 0.0
    for e in equity:
        v = float(e["equity"])
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100.0)

    wins = sum(1 for t in trades if t["side"] == "sell")
    summary = {
        "initial_cash": initial_cash,
        "final_equity": end_eq,
        "total_return_pct": round(ret_pct, 4),
        "num_trades": len(trades),
        "sell_trades": wins,
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_like_daily": round(sharpe, 4),
        "bars": n,
    }
    return {"summary": summary, "trades": trades, "equity_curve": equity}


def _downsample_equity(curve: list[dict[str, Any]], max_points: int = 400) -> list[dict[str, Any]]:
    if len(curve) <= max_points:
        return curve
    step = max(1, len(curve) // max_points)
    return curve[::step]


def run_backtest(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    """
    Run a supported strategy type on OHLCV DataFrame (columns: bar_ts, open, high, low, close, volume).
    """
    if df is None or df.empty:
        raise ValueError("No price data to backtest.")
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    need = {"open", "high", "low", "close", "bar_ts"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing columns: {missing}")

    typ = (config or {}).get("type")
    params = (config or {}).get("params") or {}
    if not typ:
        raise ValueError('Strategy config must include "type". See Indicators reference tab.')

    if typ == "sma_cross":
        buy, sell = _run_sma_cross(df, params)
    elif typ == "rsi_threshold":
        buy, sell = _run_rsi_signals(df, params)
    elif typ == "bollinger_revert":
        buy, sell = _run_bollinger_signals(df, params)
    else:
        raise ValueError(f'Unsupported strategy type "{typ}". Use sma_cross, rsi_threshold, or bollinger_revert.')

    buy = buy.reset_index(drop=True)
    sell = sell.reset_index(drop=True)
    raw = _simulate_long_only_next_open(df, buy, sell)
    raw["strategy_type"] = typ
    raw["params"] = params
    raw["equity_curve_sample"] = _downsample_equity(raw["equity_curve"])
    return raw


def results_to_storable_blob(result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Split summary vs full JSON for SQLite."""
    summary = result.get("summary") or {}
    blob = {
        "strategy_type": result.get("strategy_type"),
        "params": result.get("params"),
        "summary": summary,
        "trades": result.get("trades") or [],
        "equity_curve_sample": result.get("equity_curve_sample") or [],
    }
    return summary, json.dumps(blob, ensure_ascii=False)
