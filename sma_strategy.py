"""SMA Crossover Strategy — Golden Cross / Death Cross signal scanner + trading."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import json

import pandas as pd
import yfinance as yf

# ── Constants ──────────────────────────────────────────────────────────────

SMA_FAST          = 20
SMA_SLOW          = 50
DB_FILE           = "dashboard.sqlite"
PAPER_TRADES_FILE = Path("sma_paper_trades.json")
STARTING_CAPITAL  = 100000.0  # ₹1,00,000 paper capital

# Indices — yfinance tickers
INDICES = {
    "NIFTY 50":     "^NSEI",
    "BANK NIFTY":   "^NSEBANK",
    "FINNIFTY":     "NIFTY_FIN_SERVICE.NS",
    "MIDCAP NIFTY": "^NSEMDCP50",
    "SENSEX":       "^BSESN",
}

NIFTY50_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "WIPRO", "NESTLEIND", "POWERGRID",
    "NTPC", "TECHM", "HCLTECH", "ONGC", "BAJFINANCE",
    "BAJAJFINSV", "JSWSTEEL", "TATAMOTORS", "TATASTEEL", "ADANIENT",
    "ADANIPORTS", "COALINDIA", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "GRASIM", "HEROMOTOCO", "HINDALCO", "INDUSINDBK", "M&M",
    "CIPLA", "BPCL", "BRITANNIA", "APOLLOHOSP", "TATACONSUM",
    "SBILIFE", "HDFCLIFE", "UPL", "LTIM", "BAJAJ-AUTO",
]


# ── Database ───────────────────────────────────────────────────────────────

def init_sma_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sma_signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT 'STOCK',
            signal      TEXT NOT NULL,
            fast_sma    REAL,
            slow_sma    REAL,
            price       REAL,
            sma_gap_pct REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sma_real_trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT NOT NULL,
            symbol       TEXT NOT NULL,
            action       TEXT NOT NULL,
            qty          INTEGER NOT NULL,
            price        REAL,
            order_id     TEXT,
            status       TEXT,
            message      TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_signal_db(symbol: str, signal: str, fast_sma: float,
                   slow_sma: float, price: float, sma_gap_pct: float,
                   category: str = "STOCK") -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT INTO sma_signals
            (timestamp, symbol, category, signal, fast_sma, slow_sma, price, sma_gap_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, category,
          signal, fast_sma, slow_sma, price, sma_gap_pct))
    conn.commit()
    conn.close()


def load_signal_history(limit: int = 200) -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        f"SELECT * FROM sma_signals ORDER BY id DESC LIMIT {limit}", conn
    )
    conn.close()
    return df


def save_real_trade_db(symbol: str, action: str, qty: int, price: float,
                       order_id: str, status: str, message: str) -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT INTO sma_real_trades
            (timestamp, symbol, action, qty, price, order_id, status, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, action,
          qty, price, order_id, status, message))
    conn.commit()
    conn.close()


def load_real_trades(limit: int = 100) -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        f"SELECT * FROM sma_real_trades ORDER BY id DESC LIMIT {limit}", conn
    )
    conn.close()
    return df


# ── Paper Trade Storage ────────────────────────────────────────────────────

def load_paper_portfolio() -> dict:
    if PAPER_TRADES_FILE.exists():
        return json.loads(PAPER_TRADES_FILE.read_text())
    return {"cash": STARTING_CAPITAL, "positions": {}, "trades": []}


def save_paper_portfolio(portfolio: dict) -> None:
    PAPER_TRADES_FILE.write_text(json.dumps(portfolio, indent=2))


def place_paper_trade(symbol: str, action: str, qty: int, price: float) -> dict:
    """Execute a simulated paper trade."""
    portfolio  = load_paper_portfolio()
    total_cost = price * qty

    if action == "BUY":
        if portfolio["cash"] < total_cost:
            return {"error": f"Insufficient funds! Need ₹{total_cost:,.2f}, have ₹{portfolio['cash']:,.2f}"}
        portfolio["cash"] -= total_cost
        pos = portfolio["positions"]
        if symbol in pos:
            old_qty = pos[symbol]["qty"]
            old_avg = pos[symbol]["avg_price"]
            new_qty = old_qty + qty
            new_avg = ((old_avg * old_qty) + (price * qty)) / new_qty
            pos[symbol] = {"qty": new_qty, "avg_price": round(new_avg, 2)}
        else:
            pos[symbol] = {"qty": qty, "avg_price": price}

    elif action == "SELL":
        pos = portfolio["positions"]
        held = pos.get(symbol, {}).get("qty", 0)
        if held < qty:
            return {"error": f"Not enough shares! You hold {held}, trying to sell {qty}"}
        portfolio["cash"] += total_cost
        pos[symbol]["qty"] -= qty
        if pos[symbol]["qty"] == 0:
            del pos[symbol]

    trade = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol":    symbol,
        "action":    action,
        "qty":       qty,
        "price":     price,
        "total":     round(total_cost, 2),
        "mode":      "PAPER",
    }
    portfolio["trades"].append(trade)
    save_paper_portfolio(portfolio)
    return {"success": trade}


# ── Real Trade via Kite ────────────────────────────────────────────────────

def place_real_trade(kite, symbol: str, action: str, qty: int) -> dict:
    """
    Execute a real market order via Zerodha Kite.
    action: 'BUY' or 'SELL'
    """
    try:
        transaction = kite.TRANSACTION_TYPE_BUY if action == "BUY" else kite.TRANSACTION_TYPE_SELL
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=transaction,
            quantity=qty,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS,  # Intraday
        )
        save_real_trade_db(symbol, action, qty, 0.0, str(order_id), "PLACED", "Order placed successfully")
        return {"success": {"order_id": order_id, "symbol": symbol, "action": action, "qty": qty}}
    except Exception as e:
        save_real_trade_db(symbol, action, qty, 0.0, "", "FAILED", str(e))
        return {"error": str(e)}


# ── Data Fetch ─────────────────────────────────────────────────────────────

def fetch_data(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < SMA_SLOW + 5:
            return None
        return df
    except Exception:
        return None


def fetch_stock(symbol: str) -> pd.DataFrame | None:
    return fetch_data(f"{symbol}.NS")


def fetch_index(index_name: str) -> pd.DataFrame | None:
    ticker = INDICES.get(index_name)
    if not ticker:
        return None
    return fetch_data(ticker)


# ── Core Strategy ──────────────────────────────────────────────────────────

def compute_sma(df: pd.DataFrame, fast: int = SMA_FAST, slow: int = SMA_SLOW) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]
    if hasattr(close, "squeeze"):
        close = close.squeeze()
    df["SMA_fast"] = close.rolling(window=fast).mean()
    df["SMA_slow"] = close.rolling(window=slow).mean()
    return df


def detect_crossover(df: pd.DataFrame) -> str | None:
    if len(df) < 3:
        return None
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    fp, sp = prev["SMA_fast"], prev["SMA_slow"]
    fc, sc = curr["SMA_fast"], curr["SMA_slow"]
    if any(pd.isna([fp, sp, fc, sc])):
        return None
    if fp <= sp and fc > sc:
        return "BUY"
    if fp >= sp and fc < sc:
        return "SELL"
    return None


def _build_row(display_name: str, df: pd.DataFrame,
               fast: int, slow: int, category: str) -> dict:
    signal   = detect_crossover(df)
    last     = df.iloc[-1]
    close    = last["Close"]
    fast_sma = last["SMA_fast"]
    slow_sma = last["SMA_slow"]
    close    = float(close.iloc[0]) if hasattr(close, "__len__") else float(close)
    fast_sma = float(fast_sma)
    slow_sma = float(slow_sma)
    gap_pct  = abs(fast_sma - slow_sma) / slow_sma * 100 if slow_sma else 0
    return {
        "symbol":      display_name,
        "category":    category,
        "signal":      signal or "—",
        "price":       round(close, 2),
        "fast_sma":    round(fast_sma, 2),
        "slow_sma":    round(slow_sma, 2),
        "sma_gap_pct": round(gap_pct, 2),
        "crossover":   signal is not None,
    }


def scan_indices(fast: int = SMA_FAST, slow: int = SMA_SLOW,
                 save_to_db: bool = True) -> list[dict]:
    init_sma_db()
    results = []
    for name in INDICES:
        df = fetch_index(name)
        if df is None:
            continue
        df = compute_sma(df, fast=fast, slow=slow)
        row = _build_row(name, df, fast, slow, "INDEX")
        results.append(row)
        if row["crossover"] and save_to_db:
            save_signal_db(name, row["signal"], row["fast_sma"],
                           row["slow_sma"], row["price"], row["sma_gap_pct"], "INDEX")
    return results


def scan_stocks(symbols: list[str] | None = None, fast: int = SMA_FAST,
                slow: int = SMA_SLOW, save_to_db: bool = True) -> list[dict]:
    init_sma_db()
    if symbols is None:
        symbols = NIFTY50_STOCKS
    results = []
    for symbol in symbols:
        df = fetch_stock(symbol)
        if df is None:
            continue
        df = compute_sma(df, fast=fast, slow=slow)
        row = _build_row(symbol, df, fast, slow, "STOCK")
        results.append(row)
        if row["crossover"] and save_to_db:
            save_signal_db(symbol, row["signal"], row["fast_sma"],
                           row["slow_sma"], row["price"], row["sma_gap_pct"], "STOCK")
    return results


def get_chart_data(symbol: str, is_index: bool = False,
                   fast: int = SMA_FAST, slow: int = SMA_SLOW) -> pd.DataFrame | None:
    if is_index:
        ticker = INDICES.get(symbol)
        df = fetch_data(ticker) if ticker else None
    else:
        df = fetch_stock(symbol)
    if df is None:
        return None
    df = compute_sma(df, fast=fast, slow=slow)
    return df.dropna()
