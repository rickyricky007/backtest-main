"""RSI Strategy — tracks indices + top 50 F&O stocks."""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
import os

from alert_engine import send_telegram_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── Symbols ────────────────────────────────────────────────────────────────

INDICES = {
    "NIFTY 50":    "NSE:NIFTY 50",
    "BANKNIFTY":   "NSE:NIFTY BANK",
    "FINNIFTY":    "NSE:NIFTY FIN SERVICE",
    "SENSEX":      "BSE:SENSEX",
}

TOP_50_FO_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "WIPRO", "NESTLEIND", "BAJFINANCE",
    "HCLTECH", "TECHM", "POWERGRID", "NTPC", "ONGC",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "COALINDIA", "ADANIENT",
    "BAJAJFINSV", "DIVISLAB", "DRREDDY", "CIPLA", "EICHERMOT",
    "HEROMOTOCO", "APOLLOHOSP", "BPCL", "GRASIM", "HINDALCO",
    "INDUSINDBK", "M&M", "SBILIFE", "HDFCLIFE", "BRITANNIA",
    "UPL", "SHREECEM", "TATACONSUM", "PIDILITIND", "DMART",
]

# ── yfinance symbol map ────────────────────────────────────────────────────

YF_SYMBOL_MAP = {
    "NIFTY 50":   "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
    "SENSEX":     "^BSESN",
}

# ── RSI Single Value ───────────────────────────────────────────────────────

def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI from a list of closing prices — returns last RSI value."""
    if len(closes) < period + 1:
        return 50.0
    closes = np.array(closes)
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ── RSI Series (multiple values) ──────────────────────────────────────────

def calculate_rsi_series(closes: list[float], period: int = 14) -> list[float]:
    """
    Returns a list of RSI values — one per candle after warmup period.
    We need this to detect crossovers (compare previous RSI vs current RSI).
    """
    if len(closes) < period + 2:
        return []

    closes = np.array(closes)
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    rsi_values = []

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(round(100 - (100 / (1 + rs)), 2))

    return rsi_values


# ── Fetch OHLCV ────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str = "15m", days: int = 5) -> list[float]:
    """Fetch closing prices using yfinance."""
    try:
        import yfinance as yf
        yf_symbol = YF_SYMBOL_MAP.get(symbol, f"{symbol}.NS")
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period=f"{days}d", interval=interval)
        if hist.empty:
            return []
        return hist["Close"].dropna().tolist()
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []


# ── Format Alert Message ───────────────────────────────────────────────────

def format_signal_message(symbol: str, rsi: float, signal: str, price: float) -> str:
    emoji = "🟢" if signal == "BUY" else "🔴"
    condition = "RSI < 15 (Oversold)" if signal == "BUY" else "RSI > 85 (Overbought)"
    return (
        f"{emoji} <b>{signal} Signal!</b>\n\n"
        f"📌 Symbol: <b>{symbol}</b>\n"
        f"📊 RSI: <b>{rsi}</b>\n"
        f"📉 Condition: {condition}\n"
        f"💰 Price: ₹{price:,.2f}\n"
        f"⏰ {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
    )


def format_bounce_message(symbol: str, prev_rsi: float, curr_rsi: float, price: float) -> str:
    return (
        f"🟢 <b>RSI BOUNCE Signal!</b>\n\n"
        f"📌 Symbol: <b>{symbol}</b>\n"
        f"📊 RSI crossed above 20\n"
        f"📉 Previous RSI: <b>{prev_rsi}</b>\n"
        f"📈 Current RSI: <b>{curr_rsi}</b>\n"
        f"🎯 Target: RSI reaches 30\n"
        f"💰 Entry Price: ₹{price:,.2f}\n"
        f"⏰ {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
    )


# ── Paper Trade Entry ──────────────────────────────────────────────────────

def create_paper_trade(symbol: str, signal: str, price: float, rsi: float) -> dict:
    return {
        "symbol": symbol,
        "signal": signal,
        "entry_price": price,
        "rsi_at_entry": rsi,
        "quantity": 1,
        "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "OPEN",
        "pnl": 0.0,
    }


def create_bounce_trade(symbol: str, price: float, prev_rsi: float, curr_rsi: float) -> dict:
    return {
        "symbol": symbol,
        "strategy": "RSI Bounce",
        "entry_price": price,
        "prev_rsi": prev_rsi,
        "curr_rsi": curr_rsi,
        "target_rsi": 30,
        "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "OPEN",
    }


# ── Main RSI Scanner (existing) ────────────────────────────────────────────

def run_rsi_scanner(kite, instrument_map: dict, paper_trades: list, alerted: set) -> list[dict]:
    """Scan all symbols, check RSI level, send alerts, create paper trades."""
    signals = []
    all_symbols = list(INDICES.keys()) + TOP_50_FO_STOCKS

    for symbol in all_symbols:
        try:
            closes = fetch_ohlcv(symbol)
            if len(closes) < 15:
                continue

            rsi = calculate_rsi(closes)
            current_price = closes[-1]

            signal = None
            if rsi < 15:
                signal = "BUY"
            elif rsi > 85:
                signal = "SELL"

            if signal:
                alert_key = f"{symbol}_{signal}_{datetime.now().strftime('%Y%m%d%H%M')}"
                if alert_key not in alerted:
                    msg = format_signal_message(symbol, rsi, signal, current_price)
                    send_telegram_message(TOKEN, CHAT_ID, msg)
                    trade = create_paper_trade(symbol, signal, current_price, rsi)
                    paper_trades.append(trade)
                    alerted.add(alert_key)
                    signals.append({
                        "symbol": symbol,
                        "rsi": rsi,
                        "signal": signal,
                        "price": current_price,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    })

        except Exception as e:
            print(f"Error scanning {symbol}: {e}")
            continue

    return signals


# ── RSI Bounce Scanner (new) ───────────────────────────────────────────────

def run_rsi_bounce_scanner(alerted: set) -> list[dict]:
    """
    Bounce strategy:
    - Previous candle RSI was below 20
    - Current candle RSI crossed above 20
    - Target: RSI reaches 30
    Scans Nifty 50 on 15 min timeframe.
    """
    signals = []
    symbols = list(INDICES.keys()) + TOP_50_FO_STOCKS

    for symbol in symbols:
        try:
            closes = fetch_ohlcv(symbol, interval="15m", days=5)
            if len(closes) < 20:
                continue

            rsi_series = calculate_rsi_series(closes)

            if len(rsi_series) < 2:
                continue

            prev_rsi = rsi_series[-2]   # previous candle RSI
            curr_rsi = rsi_series[-1]   # current candle RSI
            current_price = closes[-1]

            # Crossover condition: prev below 20, current above 20
            bounce_detected = prev_rsi < 20 and curr_rsi >= 20

            if bounce_detected:
                alert_key = f"BOUNCE_{symbol}_{datetime.now().strftime('%Y%m%d%H%M')}"
                if alert_key not in alerted:
                    msg = format_bounce_message(symbol, prev_rsi, curr_rsi, current_price)
                    send_telegram_message(TOKEN, CHAT_ID, msg)
                    alerted.add(alert_key)
                    signals.append({
                        "symbol": symbol,
                        "prev_rsi": prev_rsi,
                        "curr_rsi": curr_rsi,
                        "entry_price": current_price,
                        "target_rsi": 30,
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "status": "OPEN",
                    })

        except Exception as e:
            print(f"Error in bounce scan {symbol}: {e}")
            continue

    return signals