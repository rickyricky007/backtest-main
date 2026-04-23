from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import kite_data as kd
import auth_streamlit as auth

st.set_page_config(page_title="Paper Trading", page_icon="📝", layout="wide")

auth.render_auth_cleared_banner()

# ── Files ───────────────────────────────────────
PAPER_FILE = Path("paper_trades.json")
PORTFOLIO_FILE = Path("paper_portfolio.json")


# ── Safe Load / Save ────────────────────────────
def load_trades():
    try:
        return json.loads(PAPER_FILE.read_text()) if PAPER_FILE.exists() else []
    except:
        return []


def save_trades(trades):
    PAPER_FILE.write_text(json.dumps(trades, indent=2))


def load_portfolio():
    try:
        return json.loads(PORTFOLIO_FILE.read_text()) if PORTFOLIO_FILE.exists() else {
            "cash": 100000.0,
            "holdings": {}
        }
    except:
        return {"cash": 100000.0, "holdings": {}}


def save_portfolio(p):
    PORTFOLIO_FILE.write_text(json.dumps(p, indent=2))


# ── LIVE PRICE (FIXED + SAFE + CACHED) ──────────
@st.cache_data(ttl=5)
def get_live_price(symbol: str):
    try:
        kite = kd.get_kite()
        q = kite.quote(f"NSE:{symbol}")
        return q[f"NSE:{symbol}"]["last_price"]
    except:
        return None


# ── ORDER LOGIC ─────────────────────────────────
def place_order(symbol, qty, order_type, price):
    p = load_portfolio()
    trades = load_trades()

    total = price * qty

    if order_type == "BUY":
        if p["cash"] < total:
            return {"error": "Insufficient cash"}

        p["cash"] -= total

        h = p["holdings"]
        if symbol in h:
            old_qty = h[symbol]["qty"]
            old_avg = h[symbol]["avg_price"]

            new_qty = old_qty + qty
            new_avg = ((old_avg * old_qty) + (price * qty)) / new_qty

            h[symbol] = {"qty": new_qty, "avg_price": new_avg}
        else:
            h[symbol] = {"qty": qty, "avg_price": price}

    else:  # SELL
        h = p["holdings"]

        if symbol not in h or h[symbol]["qty"] < qty:
            return {"error": "Not enough holdings"}

        p["cash"] += total
        h[symbol]["qty"] -= qty

        if h[symbol]["qty"] == 0:
            del h[symbol]

    trade = {
        "id": len(trades) + 1,
        "symbol": symbol,
        "qty": qty,
        "type": order_type,
        "price": price,
        "total": total,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    trades.append(trade)
    save_trades(trades)
    save_portfolio(p)

    return {"success": trade}


# ── Sidebar ─────────────────────────────────────
with st.sidebar:
    p = load_portfolio()
    st.metric("Cash", f"₹ {p['cash']:,.0f}")

    if st.button("Reset"):
        save_portfolio({"cash": 100000.0, "holdings": {}})
        save_trades([])
        st.rerun()

    auth.render_sidebar_kite_session()
    auth.render_logout_controls()

if not auth.ensure_kite_ready():
    st.stop()

# ── UI ──────────────────────────────────────────
st.title("📝 Paper Trading")

symbol = st.text_input("Symbol", "RELIANCE").upper()
qty = st.number_input("Qty", 1, 1000, 1)
order_type = st.radio("Type", ["BUY", "SELL"])

price = None
if symbol:
    price = get_live_price(symbol)

    if price:
        st.success(f"{symbol} ₹ {price}")
    else:
        st.warning("Price not available")

if st.button("Place Order"):

    if not price:
        st.error("No price")
    else:
        res = place_order(symbol, qty, order_type, price)

        if "error" in res:
            st.error(res["error"])
        else:
            st.success("Order placed")
            st.rerun()

# ── Portfolio ───────────────────────────────────
st.subheader("Portfolio")

p = load_portfolio()
rows = []

for sym, d in p["holdings"].items():
    cp = get_live_price(sym)
    avg = d["avg_price"]
    qty = d["qty"]

    val = (cp or avg) * qty
    pnl = val - (avg * qty)

    rows.append({
        "Symbol": sym,
        "Qty": qty,
        "Avg": avg,
        "LTP": cp,
        "P&L": pnl
    })

if rows:
    st.dataframe(pd.DataFrame(rows))
else:
    st.info("No holdings")

# ── Trades ──────────────────────────────────────
st.subheader("Trades")

tr = load_trades()

if tr:
    st.dataframe(pd.DataFrame(tr[::-1]))
else:
    st.info("No trades")