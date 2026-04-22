"""
Reference catalog of indicators you can combine with price/volume in strategy configs.

Used by the Strategies page “Indicators reference” tab. Strategy `type` + `params`
must match what `backtest_runner.run_backtest` supports.
"""

from __future__ import annotations

from typing import Any

# Each entry documents one building block; `strategy_types` lists runnable presets.
INDICATORS: list[dict[str, Any]] = [
    {
        "id": "ohlcv",
        "name": "OHLCV (raw price & volume)",
        "category": "Price & volume",
        "inputs": "Open, High, Low, Close, Volume (from Yahoo / SQLite bars)",
        "description": "Base series. Most rules compare an indicator to Close or detect crosses between two series.",
        "params": [],
        "combinations": "Cross of fast vs slow MA; price vs band; RSI vs fixed levels.",
    },
    {
        "id": "sma",
        "name": "Simple moving average (SMA)",
        "category": "Trend",
        "inputs": "Typically Close; can be applied to High/Low in custom code.",
        "description": "Arithmetic mean over the last n bars. Smooths noise; lag increases with n.",
        "params": [{"name": "period", "type": "int", "example": 20}],
        "combinations": "Price vs SMA; SMA(fast) vs SMA(slow) cross (used by strategy type `sma_cross`).",
    },
    {
        "id": "ema",
        "name": "Exponential moving average (EMA)",
        "category": "Trend",
        "inputs": "Close (typical).",
        "description": "Weighted average favouring recent prices; reacts faster than SMA for the same period.",
        "params": [{"name": "period", "type": "int", "example": 12}],
        "combinations": "EMA cross pairs; MACD uses 12/26 EMA.",
    },
    {
        "id": "rsi",
        "name": "Relative strength index (RSI)",
        "category": "Momentum",
        "inputs": "Close.",
        "description": "0–100 oscillator. Often used with oversold/overbought thresholds (e.g. 30 / 70).",
        "params": [
            {"name": "period", "type": "int", "example": 14},
            {"name": "oversold", "type": "float", "example": 30},
            {"name": "overbought", "type": "float", "example": 70},
        ],
        "combinations": "Mean reversion vs levels; filter trend trades when RSI extremes.",
        "strategy_types": ["rsi_threshold"],
    },
    {
        "id": "macd",
        "name": "MACD (line, signal, histogram)",
        "category": "Momentum",
        "inputs": "Close.",
        "description": "Trend/momentum from EMA spread. Histogram = MACD − signal.",
        "params": [
            {"name": "fast", "type": "int", "example": 12},
            {"name": "slow", "type": "int", "example": 26},
            {"name": "signal", "type": "int", "example": 9},
        ],
        "combinations": "MACD/Signal cross; histogram sign flips (not yet a built-in strategy type).",
    },
    {
        "id": "bollinger",
        "name": "Bollinger Bands",
        "category": "Volatility",
        "inputs": "Close.",
        "description": "Middle = SMA(window); upper/lower = middle ± k·rolling std.",
        "params": [
            {"name": "window", "type": "int", "example": 20},
            {"name": "num_std", "type": "float", "example": 2.0},
        ],
        "combinations": "Price touch lower/upper for mean reversion (see `bollinger_revert`).",
        "strategy_types": ["bollinger_revert"],
    },
    {
        "id": "atr",
        "name": "Average true range (ATR)",
        "category": "Volatility",
        "inputs": "High, Low, Close.",
        "description": "Average range; common for stop sizing and volatility filters.",
        "params": [{"name": "period", "type": "int", "example": 14}],
        "combinations": "Stops = entry ± k·ATR; avoid entries when ATR percentile high.",
    },
    {
        "id": "stochastic",
        "name": "Stochastic oscillator (%K / %D)",
        "category": "Momentum",
        "inputs": "High, Low, Close.",
        "description": "Position of close within recent high–low range; smoothed %D.",
        "params": [
            {"name": "k_period", "type": "int", "example": 14},
            {"name": "d_period", "type": "int", "example": 3},
        ],
        "combinations": "Cross of %K and %D; extremes with RSI.",
    },
    {
        "id": "obv",
        "name": "On-balance volume (OBV)",
        "category": "Volume",
        "inputs": "Close, Volume.",
        "description": "Cumulative signed volume by close-to-close direction.",
        "params": [],
        "combinations": "OBV trend vs price trend (divergence ideas).",
    },
    {
        "id": "vwap_session",
        "name": "VWAP (session / anchored)",
        "category": "Volume & price",
        "inputs": "Typical price × Volume (needs intraday data).",
        "description": "Volume-weighted average price; common intraday benchmark (not precomputed in runner).",
        "params": [{"name": "anchor", "type": "str", "example": "session"}],
        "combinations": "Price above VWAP bias; mean reversion to VWAP.",
    },
    {
        "id": "roc",
        "name": "Rate of change (ROC / momentum %)",
        "category": "Momentum",
        "inputs": "Close.",
        "description": "Percent change over n bars.",
        "params": [{"name": "period", "type": "int", "example": 10}],
        "combinations": "Breakout filters with ROC > threshold.",
    },
    {
        "id": "adx",
        "name": "Average directional index (ADX)",
        "category": "Trend strength",
        "inputs": "High, Low, Close.",
        "description": "Strength of trend (not direction). Often paired with +DI/−DI.",
        "params": [{"name": "period", "type": "int", "example": 14}],
        "combinations": "Only take MA crosses when ADX > 25.",
    },
]

STRATEGY_TYPE_HELP: list[dict[str, Any]] = [
    {
        "type": "sma_cross",
        "title": "SMA fast / slow crossover (trend)",
        "config_example": {
            "type": "sma_cross",
            "params": {"fast_period": 10, "slow_period": 50},
        },
        "rules": "Long on bullish cross (fast crosses above slow); flat on bearish cross. Trades execute on **next bar open**.",
    },
    {
        "type": "rsi_threshold",
        "title": "RSI mean reversion",
        "config_example": {
            "type": "rsi_threshold",
            "params": {"period": 14, "oversold": 30, "overbought": 70},
        },
        "rules": "Buy next open when RSI < oversold; sell next open when RSI > overbought. Single long-or-flat position.",
    },
    {
        "type": "bollinger_revert",
        "title": "Bollinger mean reversion",
        "config_example": {
            "type": "bollinger_revert",
            "params": {"window": 20, "num_std": 2.0},
        },
        "rules": "Buy next open when close < lower band; sell next open when close >= middle band.",
    },
]


def indicators_by_category() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in INDICATORS:
        cat = row.get("category") or "Other"
        out.setdefault(cat, []).append(row)
    return out
