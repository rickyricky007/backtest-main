"""
SMA Crossover Strategy — PRO VERSION
Includes:
✔ P&L tracking
✔ Position sizing (risk-based)
✔ Stop-loss & target
✔ Multi-timeframe confirmation
✔ Auto scanning ready
"""

from __future__ import annotations
from datetime import datetime
import pandas as pd
import yfinance as yf
import json
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# ⚙️ CONFIG
# ─────────────────────────────────────────────────────────────

SMA_FAST = 20
SMA_SLOW = 50

STARTING_CAPITAL = 100000
RISK_PER_TRADE = 0.02   # 2% risk per trade
RR_RATIO = 2            # Risk:Reward = 1:2

PAPER_FILE = Path("sma_portfolio.json")

# ─────────────────────────────────────────────────────────────
# 📊 DATA FETCH
# ─────────────────────────────────────────────────────────────

def fetch_data(symbol, interval="1d"):
    try:
        df = yf.download(symbol, period="6mo", interval=interval, progress=False)
        if df.empty:
            return None
        return df
    except:
        return None

# ─────────────────────────────────────────────────────────────
# 📈 INDICATORS
# ─────────────────────────────────────────────────────────────

def add_sma(df):
    df["SMA_FAST"] = df["Close"].rolling(SMA_FAST).mean()
    df["SMA_SLOW"] = df["Close"].rolling(SMA_SLOW).mean()
    return df

def detect_signal(df):
    if len(df) < SMA_SLOW:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    if prev["SMA_FAST"] < prev["SMA_SLOW"] and curr["SMA_FAST"] > curr["SMA_SLOW"]:
        return "BUY"

    if prev["SMA_FAST"] > prev["SMA_SLOW"] and curr["SMA_FAST"] < curr["SMA_SLOW"]:
        return "SELL"

    return None

# ─────────────────────────────────────────────────────────────
# 🧠 MULTI-TIMEFRAME CONFIRMATION
# ─────────────────────────────────────────────────────────────

def multi_timeframe_signal(symbol):
    df_1d = fetch_data(symbol, "1d")
    df_1h = fetch_data(symbol, "1h")

    if df_1d is None or df_1h is None:
        return None

    df_1d = add_sma(df_1d)
    df_1h = add_sma(df_1h)

    sig1 = detect_signal(df_1d)
    sig2 = detect_signal(df_1h)

    if sig1 == sig2:
        return sig1

    return None

# ─────────────────────────────────────────────────────────────
# 💰 POSITION SIZING (PRO LEVEL)
# ─────────────────────────────────────────────────────────────

def calculate_position_size(capital, entry, stop_loss):
    risk_amount = capital * RISK_PER_TRADE
    risk_per_share = abs(entry - stop_loss)

    if risk_per_share == 0:
        return 0

    qty = int(risk_amount / risk_per_share)
    return max(qty, 1)

# ─────────────────────────────────────────────────────────────
# 📦 PORTFOLIO
# ─────────────────────────────────────────────────────────────

def load_portfolio():
    if PAPER_FILE.exists():
        return json.loads(PAPER_FILE.read_text())
    return {
        "cash": STARTING_CAPITAL,
        "positions": {},
        "trades": []
    }

def save_portfolio(p):
    PAPER_FILE.write_text(json.dumps(p, indent=2))

# ─────────────────────────────────────────────────────────────
# 📊 TRADE EXECUTION
# ─────────────────────────────────────────────────────────────

def place_trade(symbol, signal, price):
    portfolio = load_portfolio()

    # Define SL + Target
    if signal == "BUY":
        stop_loss = price * 0.98
        target = price * (1 + (1 - 0.98) * RR_RATIO)
    else:
        stop_loss = price * 1.02
        target = price * (1 - (1.02 - 1) * RR_RATIO)

    qty = calculate_position_size(portfolio["cash"], price, stop_loss)

    if qty == 0:
        return {"error": "Position size = 0"}

    total = qty * price

    if signal == "BUY":
        if portfolio["cash"] < total:
            return {"error": "Not enough capital"}

        portfolio["cash"] -= total
        portfolio["positions"][symbol] = {
            "qty": qty,
            "entry": price,
            "sl": stop_loss,
            "target": target,
            "side": "LONG"
        }

    elif signal == "SELL":
        portfolio["cash"] += total
        portfolio["positions"][symbol] = {
            "qty": qty,
            "entry": price,
            "sl": stop_loss,
            "target": target,
            "side": "SHORT"
        }

    trade = {
        "time": str(datetime.now()),
        "symbol": symbol,
        "signal": signal,
        "price": price,
        "qty": qty
    }

    portfolio["trades"].append(trade)
    save_portfolio(portfolio)

    return {"success": trade}

# ─────────────────────────────────────────────────────────────
# 📊 P&L CALCULATION
# ─────────────────────────────────────────────────────────────

def calculate_pnl():
    portfolio = load_portfolio()
    total_pnl = 0

    for sym, pos in portfolio["positions"].items():
        df = fetch_data(sym)
        if df is None:
            continue

        current_price = df["Close"].iloc[-1]

        if pos["side"] == "LONG":
            pnl = (current_price - pos["entry"]) * pos["qty"]
        else:
            pnl = (pos["entry"] - current_price) * pos["qty"]

        total_pnl += pnl

    return round(total_pnl, 2)

# ─────────────────────────────────────────────────────────────
# 🔄 AUTO SCANNER
# ─────────────────────────────────────────────────────────────

WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
    "^NSEI", "^NSEBANK"
]

def run_auto_scan():
    signals = []

    for sym in WATCHLIST:
        signal = multi_timeframe_signal(sym)

        if signal:
            df = fetch_data(sym)
            price = df["Close"].iloc[-1]

            trade = place_trade(sym, signal, price)

            signals.append({
                "symbol": sym,
                "signal": signal,
                "price": price,
                "trade": trade
            })

    return signals