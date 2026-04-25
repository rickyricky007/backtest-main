"""
Backtest Engine — Phase 5
==========================
Proper backtesting with professional metrics.

Features:
    - Run any strategy against historical OHLCV data
    - Full trade log with entry/exit prices
    - Metrics: P&L, Sharpe, Sortino, Max Drawdown, Win Rate, Profit Factor
    - Walk-forward testing (out-of-sample validation)
    - Parameter optimization (grid search)
    - Equity curve generation

Usage:
    from backtest_engine import BacktestEngine
    from strategies import RSIStrategy

    engine = BacktestEngine(capital=100000)
    result = engine.run(
        strategy_class = RSIStrategy,
        strategy_params = {"symbol": "RELIANCE", "period": 14},
        symbol  = "RELIANCE",
        interval= "day",
        days    = 365,
    )
    print(result.summary())
    result.plot()
"""

from __future__ import annotations

import math
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Type

import numpy as np
import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE & RESULT DATACLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    symbol:      str
    action:      str          # BUY or SELL
    entry_time:  datetime
    entry_price: float
    quantity:    int
    exit_time:   datetime | None = None
    exit_price:  float | None   = None
    exit_reason: str            = ""

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        if self.action == "BUY":
            return (self.exit_price - self.entry_price) * self.quantity
        return (self.entry_price - self.exit_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        if not self.entry_price:
            return 0.0
        return self.pnl / (self.entry_price * self.quantity) * 100

    @property
    def duration(self) -> str:
        if not self.exit_time:
            return "Open"
        delta = self.exit_time - self.entry_time
        return str(delta)


@dataclass
class BacktestResult:
    symbol:       str
    strategy:     str
    params:       dict
    trades:       list[Trade]
    equity_curve: pd.Series
    capital:      float
    start_date:   str
    end_date:     str

    # ── Computed metrics ──────────────────────────────────────────────────────

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losing_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winning_trades) / len(self.trades) * 100

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.capital * 100

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.winning_trades]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [abs(t.pnl) for t in self.losing_trades]
        return sum(losses) / len(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.winning_trades)
        gross_loss   = abs(sum(t.pnl for t in self.losing_trades))
        return round(gross_profit / gross_loss, 2) if gross_loss else float("inf")

    @property
    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown in ₹."""
        if self.equity_curve.empty:
            return 0.0
        peak     = self.equity_curve.cummax()
        drawdown = (self.equity_curve - peak)
        return float(drawdown.min())

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        peak     = self.equity_curve.cummax()
        drawdown = (self.equity_curve - peak) / peak * 100
        return float(drawdown.min())

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio (risk-free rate = 6.5%)."""
        returns = self.equity_curve.pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        rf_daily = 0.065 / 252
        excess   = returns - rf_daily
        std      = excess.std()
        if std == 0:
            return 0.0
        return round(float(excess.mean() / std * math.sqrt(252)), 2)

    @property
    def sortino_ratio(self) -> float:
        """Sortino ratio — penalizes only downside volatility."""
        returns = self.equity_curve.pct_change().dropna()
        if len(returns) < 2:
            return 0.0
        rf_daily    = 0.065 / 252
        excess      = returns - rf_daily
        downside    = excess[excess < 0]
        downside_std = downside.std()
        if downside_std == 0:
            return 0.0
        return round(float(excess.mean() / downside_std * math.sqrt(252)), 2)

    @property
    def calmar_ratio(self) -> float:
        """Annual return / Max drawdown — measures return per unit of drawdown risk."""
        if self.max_drawdown_pct == 0:
            return 0.0
        return round(self.total_pnl_pct / abs(self.max_drawdown_pct), 2)

    def summary(self) -> dict:
        return {
            "strategy":          self.strategy,
            "symbol":            self.symbol,
            "period":            f"{self.start_date} → {self.end_date}",
            "capital":           f"₹{self.capital:,.0f}",
            "total_trades":      self.total_trades,
            "win_rate":          f"{self.win_rate:.1f}%",
            "total_pnl":         f"₹{self.total_pnl:+,.2f}",
            "total_pnl_%":       f"{self.total_pnl_pct:+.2f}%",
            "avg_win":           f"₹{self.avg_win:,.2f}",
            "avg_loss":          f"₹{self.avg_loss:,.2f}",
            "profit_factor":     self.profit_factor,
            "max_drawdown":      f"₹{self.max_drawdown:,.2f}",
            "max_drawdown_%":    f"{self.max_drawdown_pct:.2f}%",
            "sharpe_ratio":      self.sharpe_ratio,
            "sortino_ratio":     self.sortino_ratio,
            "calmar_ratio":      self.calmar_ratio,
        }

    def trades_df(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "entry_time":  t.entry_time.strftime("%Y-%m-%d %H:%M"),
            "exit_time":   t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "Open",
            "action":      t.action,
            "entry_price": t.entry_price,
            "exit_price":  t.exit_price,
            "quantity":    t.quantity,
            "pnl":         round(t.pnl, 2),
            "pnl_%":       round(t.pnl_pct, 2),
            "exit_reason": t.exit_reason,
        } for t in self.trades])


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class BacktestEngine:

    def __init__(self, capital: float = 100_000.0):
        self.capital = capital

    # ── Fetch data ────────────────────────────────────────────────────────────

    def _fetch_data(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        """Fetch historical OHLCV from Kite API."""
        from datetime import timedelta
        import kite_data as kd
        from kiteconnect import KiteConnect

        kite = kd.kite_client()
        inst = kite.instruments("NSE")
        token_map = {i["tradingsymbol"]: i["instrument_token"] for i in inst}
        token = token_map.get(symbol.upper())
        if not token:
            raise ValueError(f"Instrument not found: {symbol}")

        to_date   = datetime.now()
        from_date = to_date - timedelta(days=days)
        data = kite.historical_data(token, from_date, to_date, interval)

        if not data:
            raise ValueError(f"No historical data for {symbol}")

        df = pd.DataFrame(data)
        df.set_index("date", inplace=True)
        df.rename(columns={"open":"Open","high":"High",
                            "low":"Low","close":"Close","volume":"Volume"}, inplace=True)
        return df

    # ── Run single backtest ───────────────────────────────────────────────────

    def run(
        self,
        strategy_class:  Type[BaseStrategy],
        strategy_params: dict,
        symbol:          str,
        interval:        str   = "day",
        days:            int   = 365,
        sl_pct:          float = 2.0,    # stop loss % from entry
        target_pct:      float = 4.0,    # target % from entry
    ) -> BacktestResult:
        """
        Run a strategy against historical data.

        strategy_class  : e.g. RSIStrategy
        strategy_params : e.g. {"symbol": "RELIANCE", "period": 14}
        sl_pct          : stop loss % below entry for BUY (above for SELL)
        target_pct      : take profit % above entry for BUY
        """
        df = self._fetch_data(symbol, interval, days)

        strat  = strategy_class(**strategy_params, mode="PAPER")
        trades: list[Trade] = []
        equity = self.capital
        eq_series: list[float] = [equity]
        eq_index:  list        = [df.index[0]]

        open_trade: Trade | None = None

        for ts, row in df.iterrows():
            price = float(row["Close"])
            tick  = {
                "last_price":       price,
                "instrument_token": 0,
                "volume_traded":    int(row.get("Volume", 0)),
                "ohlc": {
                    "open":  float(row["Open"]),
                    "high":  float(row["High"]),
                    "low":   float(row["Low"]),
                    "close": float(row["Close"]),
                },
            }

            # Check SL / target for open trade
            if open_trade and open_trade.exit_price is None:
                if open_trade.action == "BUY":
                    sl_price     = open_trade.entry_price * (1 - sl_pct / 100)
                    target_price = open_trade.entry_price * (1 + target_pct / 100)
                    if price <= sl_price:
                        open_trade.exit_price  = sl_price
                        open_trade.exit_time   = ts
                        open_trade.exit_reason = "Stop loss"
                        equity += open_trade.pnl
                        trades.append(open_trade)
                        open_trade = None
                    elif price >= target_price:
                        open_trade.exit_price  = target_price
                        open_trade.exit_time   = ts
                        open_trade.exit_reason = "Target"
                        equity += open_trade.pnl
                        trades.append(open_trade)
                        open_trade = None
                else:  # SELL
                    sl_price     = open_trade.entry_price * (1 + sl_pct / 100)
                    target_price = open_trade.entry_price * (1 - target_pct / 100)
                    if price >= sl_price:
                        open_trade.exit_price  = sl_price
                        open_trade.exit_time   = ts
                        open_trade.exit_reason = "Stop loss"
                        equity += open_trade.pnl
                        trades.append(open_trade)
                        open_trade = None
                    elif price <= target_price:
                        open_trade.exit_price  = target_price
                        open_trade.exit_time   = ts
                        open_trade.exit_reason = "Target"
                        equity += open_trade.pnl
                        trades.append(open_trade)
                        open_trade = None

            # Run strategy
            sig = strat.on_tick(tick)

            if sig and sig.action in ("BUY", "SELL") and open_trade is None:
                qty = max(1, int(equity * 0.1 / price))  # use 10% of equity
                open_trade = Trade(
                    symbol      = symbol,
                    action      = sig.action,
                    entry_time  = ts,
                    entry_price = price,
                    quantity    = qty,
                )

            elif sig and sig.action in ("EXIT", "EXIT_SHORT") and open_trade:
                open_trade.exit_price  = price
                open_trade.exit_time   = ts
                open_trade.exit_reason = "Strategy exit"
                equity += open_trade.pnl
                trades.append(open_trade)
                open_trade = None

            eq_series.append(equity)
            eq_index.append(ts)

        # Close any open trade at last price
        if open_trade:
            last_price = float(df["Close"].iloc[-1])
            open_trade.exit_price  = last_price
            open_trade.exit_time   = df.index[-1]
            open_trade.exit_reason = "End of data"
            equity += open_trade.pnl
            trades.append(open_trade)

        eq_curve = pd.Series(eq_series, index=eq_index[:len(eq_series)])

        return BacktestResult(
            symbol       = symbol,
            strategy     = strat.name,
            params       = strategy_params,
            trades       = trades,
            equity_curve = eq_curve,
            capital      = self.capital,
            start_date   = str(df.index[0])[:10],
            end_date     = str(df.index[-1])[:10],
        )

    # ── Walk-forward testing ──────────────────────────────────────────────────

    def walk_forward(
        self,
        strategy_class:  Type[BaseStrategy],
        strategy_params: dict,
        symbol:          str,
        total_days:      int = 730,
        train_days:      int = 365,
        test_days:       int = 90,
        interval:        str = "day",
    ) -> list[BacktestResult]:
        """
        Walk-forward test: train on in-sample, test on out-of-sample.
        Repeats sliding the window forward by test_days each iteration.

        Returns list of BacktestResult for each test window.
        """
        results = []
        offset  = 0

        while offset + train_days + test_days <= total_days:
            # Test window
            test_start_days = total_days - offset - test_days
            try:
                result = self.run(
                    strategy_class  = strategy_class,
                    strategy_params = strategy_params,
                    symbol          = symbol,
                    interval        = interval,
                    days            = test_start_days + test_days,
                )
                results.append(result)
                print(f"[WalkForward] Window {len(results)}: "
                      f"P&L={result.total_pnl:+,.0f} Sharpe={result.sharpe_ratio}")
            except Exception as e:
                print(f"[WalkForward] Window failed: {e}")

            offset += test_days

        return results

    # ── Parameter optimization ────────────────────────────────────────────────

    def optimize(
        self,
        strategy_class:  Type[BaseStrategy],
        base_params:     dict,
        param_grid:      dict[str, list],
        symbol:          str,
        interval:        str   = "day",
        days:            int   = 365,
        metric:          str   = "sharpe_ratio",   # or "total_pnl", "win_rate"
    ) -> list[dict]:
        """
        Grid search over parameter combinations.

        param_grid: {"period": [7, 14, 21], "oversold": [25, 30, 35]}
        metric    : what to optimize for

        Returns sorted list of (params, metric_value, result.summary())
        """
        keys   = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(itertools.product(*values))

        print(f"[Optimize] Testing {len(combos)} combinations for {metric}…")
        results = []

        for combo in combos:
            params = {**base_params, **dict(zip(keys, combo))}
            try:
                result = self.run(
                    strategy_class  = strategy_class,
                    strategy_params = params,
                    symbol          = symbol,
                    interval        = interval,
                    days            = days,
                )
                score = getattr(result, metric, 0)
                if callable(score):
                    score = score()
                results.append({
                    "params":  params,
                    "score":   score,
                    "summary": result.summary(),
                })
                print(f"  {dict(zip(keys, combo))} → {metric}={score}")
            except Exception as e:
                print(f"  {dict(zip(keys, combo))} → Error: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)
        print(f"\n[Optimize] Best: {results[0]['params']} → {metric}={results[0]['score']}")
        return results
