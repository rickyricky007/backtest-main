"""Paper Trading — simulate trades with real market prices from Kite."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import kite_data as kd
import auth_streamlit as auth

st.set_page_config(
    page_title="Paper Trading",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

auth.render_auth_cleared_banner()

# ── Storage ────────────────────────────────────────────────────────────────
PAPER_FILE = Path("paper_trades.json")
PORTFOLIO_FILE = Path("paper_portfolio.json")

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


def load_trades() -> list:
    if PAPER_FILE.exists():
        return json.loads(PAPER_FILE.read_text())
    return []


def save_trades(trades: list) -> None:
    PAPER_FILE.write_text(json.dumps(trades, indent=2))


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text())
    return {"cash": 100000.0, "holdings": {}}


def save_portfolio(portfolio: dict) -> None:
    PORTFOLIO_FILE.write_text(json.dumps(portfolio, indent=2))


def get_live_price(symbol: str) -> float | None:
    try:
        quote = kd.kite().quote(f"NSE:{symbol}")
        return quote[f"NSE:{symbol}"]["last_price"]
    except Exception:
        return None


def place_order(symbol: str, qty: int, order_type: str, price: float) -> dict:
    portfolio = load_portfolio()
    trades = load_trades()
    total_value = price * qty

    if order_type == "BUY":
        if portfolio["cash"] < total_value:
            return {"error": f"Insufficient cash! Need ₹{total_value:,.2f}, have ₹{portfolio['cash']:,.2f}"}
        portfolio["cash"] -= total_value
        holdings = portfolio["holdings"]
        if symbol in holdings:
            # average price calculation
            existing_qty = holdings[symbol]["qty"]
            existing_avg = holdings[symbol]["avg_price"]
            new_qty = existing_qty + qty
            new_avg = ((existing_qty * existing_avg) + (qty * price)) / new_qty
            holdings[symbol] = {"qty": new_qty, "avg_price": new_avg}
        else:
            holdings[symbol] = {"qty": qty, "avg_price": price}

    elif order_type == "SELL":
        holdings = portfolio["holdings"]
        if symbol not in holdings or holdings[symbol]["qty"] < qty:
            held = holdings.get(symbol, {}).get("qty", 0)
            return {"error": f"Insufficient holdings! You hold {held} shares of {symbol}"}
        portfolio["cash"] += total_value
        holdings[symbol]["qty"] -= qty
        if holdings[symbol]["qty"] == 0:
            del holdings[symbol]

    trade = {
        "id": len(trades) + 1,
        "symbol": symbol,
        "qty": qty,
        "order_type": order_type,
        "price": price,
        "total": total_value,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    trades.append(trade)
    save_trades(trades)
    save_portfolio(portfolio)
    return {"success": trade}


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("💰 Paper Portfolio")
    portfolio = load_portfolio()
    st.metric("Available Cash", f"₹ {portfolio['cash']:,.2f}")
    st.divider()

    if st.button("🔄 Reset Portfolio", use_container_width=True):
        save_portfolio({"cash": 100000.0, "holdings": {}})
        save_trades([])
        st.success("Portfolio reset to ₹1,00,000!")
        st.rerun()

    auth.render_sidebar_kite_session(key_prefix="paper")
    auth.render_logout_controls(key="kite_logout_paper")

if not auth.ensure_kite_ready():
    st.stop()

# ── Header ─────────────────────────────────────────────────────────────────
st.title("📝 Paper Trading")
st.caption("Simulate trades with real-time Kite prices. Starting capital: ₹1,00,000")

portfolio = load_portfolio()
trades = load_trades()

# ── Place Order ────────────────────────────────────────────────────────────
st.subheader("Place Order")

col1, col2 = st.columns(2)

with col1:
    stock_source = st.radio("Stock selection", ["Nifty 50", "Type manually"], horizontal=True)
    if stock_source == "Nifty 50":
        symbol = st.selectbox("Select stock", NIFTY50_STOCKS)
    else:
        symbol = st.text_input("Enter stock symbol", placeholder="e.g. RELIANCE").upper().strip()

with col2:
    order_type = st.radio("Order type", ["BUY", "SELL"], horizontal=True)
    qty = st.number_input("Quantity", min_value=1, value=1, step=1)

# Fetch live price
if symbol:
    price_placeholder = st.empty()
    live_price = get_live_price(symbol)
    if live_price:
        price_placeholder.success(f"📡 Live price of **{symbol}**: ₹ {live_price:,.2f}")
        total_cost = live_price * qty
        st.info(f"💸 Total {'Cost' if order_type == 'BUY' else 'Value'}: ₹ {total_cost:,.2f}")
    else:
        price_placeholder.warning(f"⚠️ Could not fetch price for {symbol}. Check symbol name.")
        live_price = None

    if st.button(f"{'🟢 BUY' if order_type == 'BUY' else '🔴 SELL'} {symbol}", type="primary", use_container_width=True):
        if not live_price:
            st.error("Cannot place order — price not available!")
        else:
            result = place_order(symbol, qty, order_type, live_price)
            if "error" in result:
                st.error(result["error"])
            else:
                t = result["success"]
                st.success(f"✅ {t['order_type']} {t['qty']} shares of {t['symbol']} @ ₹{t['price']:,.2f}")
                st.rerun()

st.divider()

# ── Portfolio Summary ──────────────────────────────────────────────────────
st.subheader("📊 Portfolio Summary")

portfolio = load_portfolio()
holdings = portfolio["holdings"]

if holdings:
    rows = []
    total_invested = 0
    total_current = 0

    for sym, data in holdings.items():
        current_price = get_live_price(sym)
        avg_price = data["avg_price"]
        hold_qty = data["qty"]
        invested = avg_price * hold_qty
        current = (current_price or avg_price) * hold_qty
        pnl = current - invested
        pnl_pct = (pnl / invested) * 100 if invested else 0
        total_invested += invested
        total_current += current

        rows.append({
            "Symbol": sym,
            "Qty": hold_qty,
            "Avg Price": f"₹ {avg_price:,.2f}",
            "Current Price": f"₹ {current_price:,.2f}" if current_price else "N/A",
            "Invested": f"₹ {invested:,.2f}",
            "Current Value": f"₹ {current:,.2f}",
            "P&L": f"₹ {pnl:,.2f}",
            "P&L %": f"{pnl_pct:.2f}%",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested) * 100 if total_invested else 0
    net_worth = portfolio["cash"] + total_current

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Cash Balance", f"₹ {portfolio['cash']:,.2f}")
    with c2:
        st.metric("Invested Value", f"₹ {total_invested:,.2f}")
    with c3:
        st.metric("Current Value", f"₹ {total_current:,.2f}")
    with c4:
        st.metric("Total P&L", f"₹ {total_pnl:,.2f}", delta=f"{total_pnl_pct:.2f}%")

    st.metric("💰 Net Worth", f"₹ {net_worth:,.2f}",
              delta=f"₹ {net_worth - 100000:,.2f} from ₹1,00,000")
else:
    st.info("No holdings yet. Place your first order above! 👆")

st.divider()

# ── Trade History ──────────────────────────────────────────────────────────
st.subheader("📋 Trade History")

trades = load_trades()
if trades:
    trades_reversed = list(reversed(trades))
    tdf = pd.DataFrame(trades_reversed)
    tdf = tdf[["id", "timestamp", "symbol", "order_type", "qty", "price", "total"]]
    tdf.columns = ["#", "Time", "Symbol", "Type", "Qty", "Price", "Total Value"]
    tdf["Price"] = tdf["Price"].apply(lambda x: f"₹ {x:,.2f}")
    tdf["Total Value"] = tdf["Total Value"].apply(lambda x: f"₹ {x:,.2f}")
    st.dataframe(tdf, use_container_width=True, hide_index=True, height=300)

    if st.button("🗑️ Clear Trade History", use_container_width=False):
        save_trades([])
        st.success("Trade history cleared!")
        st.rerun()
else:
    st.info("No trades yet. Start trading! 🚀")
