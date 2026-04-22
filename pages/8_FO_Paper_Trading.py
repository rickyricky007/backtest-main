"""F&O Paper Trading — simulate options/futures trading with real Kite prices."""

from __future__ import annotations

import json
import time
import calendar
from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st

import kite_data as kd
import auth_streamlit as auth
import local_store as store
import alert_engine as ae

st.set_page_config(
    page_title="F&O Paper Trading",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

auth.render_auth_cleared_banner()

# ── Constants ──────────────────────────────────────────────────────────────

INDICES = {
    "NIFTY":      {"lot": 50,  "symbol": "NIFTY 50",          "exchange": "NFO"},
    "BANKNIFTY":  {"lot": 15,  "symbol": "NIFTY BANK",        "exchange": "NFO"},
    "FINNIFTY":   {"lot": 40,  "symbol": "NIFTY FIN SERVICE", "exchange": "NFO"},
    "MIDCPNIFTY": {"lot": 75,  "symbol": "NIFTY MID SELECT",  "exchange": "NFO"},
    "SENSEX":     {"lot": 10,  "symbol": "SENSEX",            "exchange": "BFO"},
}

# Spot exchange for each index (for live price fetch)
INDEX_SPOT_EXCHANGE = {
    "NIFTY": "NSE", "BANKNIFTY": "NSE", "FINNIFTY": "NSE",
    "MIDCPNIFTY": "NSE", "SENSEX": "BSE",
}

FO_STOCKS = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
    "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","TITAN",
    "SUNPHARMA","ULTRACEMCO","WIPRO","NESTLEIND","POWERGRID","NTPC","TECHM",
    "HCLTECH","ONGC","BAJFINANCE","BAJAJFINSV","JSWSTEEL","TATAMOTORS",
    "TATASTEEL","ADANIENT","ADANIPORTS","COALINDIA","DIVISLAB","DRREDDY",
    "EICHERMOT","GRASIM","HEROMOTOCO","HINDALCO","INDUSINDBK","M&M","CIPLA",
    "BPCL","BRITANNIA","APOLLOHOSP","TATACONSUM","SBILIFE","HDFCLIFE",
    "UPL","LTIM","BAJAJ-AUTO","AMBUJACEM","AUROPHARMA","BANDHANBNK",
    "BERGEPAINT","BIOCON","BOSCHLTD","CANBK","CHOLAFIN","CONCOR","COFORGE",
    "COLPAL","CUMMINSIND","DABUR","DLF","ESCORTS","FEDERALBNK","GLENMARK",
    "GMRINFRA","GRANULES","HAVELLS","HINDPETRO","IBULHSGFIN","IDEA",
    "IDFCFIRSTB","IGL","INDHOTEL","INDUSTOWER","IRCTC","JUBLFOOD","LALPATHLAB",
    "LICHSGFIN","LUPIN","MANAPPURAM","MCDOWELL-N","METROPOLIS","MFSL",
    "MOTHERSON","MPHASIS","MRF","MUTHOOTFIN","NAUKRI","OBEROIRLTY","OFSS",
    "PAGEIND","PEL","PERSISTENT","PETRONET","PFC","PIDILITIND","PIIND",
    "PNB","POLYCAB","PVRINOX","RAMCOCEM","RBLBANK","RECLTD","SAIL",
    "SIEMENS","SRF","STAR","SUNTV","SYNGENE","TORNTPHARM","TRENT",
    "TVSMOTOR","UNIONBANK","VEDL","VOLTAS","ZYDUSLIFE",
]

FO_STOCKS_LOT = {s: 500 for s in FO_STOCKS}
FO_STOCKS_LOT.update({
    "MRF": 10, "PAGEIND": 15, "BOSCHLTD": 25, "EICHERMOT": 50,
    "MARUTI": 25, "NESTLEIND": 50, "TITAN": 175, "RELIANCE": 250,
    "TCS": 150, "INFY": 300, "HDFCBANK": 550, "ICICIBANK": 700,
})

# ── Storage (SQLite) ───────────────────────────────────────────────────────

STARTING_CAPITAL = 500_000.0  # ₹5,00,000


def load_fo_trades() -> list:
    return store.load_fo_trades()


def save_fo_trades(trades: list) -> None:
    pass  # individual inserts happen via store.append_fo_trade() in place_fo_order()


def load_fo_portfolio() -> dict:
    return store.load_fo_portfolio(starting_capital=STARTING_CAPITAL)


def save_fo_portfolio(portfolio: dict) -> None:
    store.save_fo_portfolio(portfolio)


# ── Expiry Helpers ─────────────────────────────────────────────────────────

def get_weekly_expiries(n: int = 5) -> list[str]:
    """Get next N weekly expiries (Thursdays)."""
    expiries = []
    today = date.today()
    d = today
    while len(expiries) < n:
        if d.weekday() == 3:  # Thursday
            expiries.append(d.strftime("%d %b %Y"))
        d += timedelta(days=1)
    return expiries


def get_monthly_expiries(n: int = 3) -> list[str]:
    """Get next N monthly expiries (last Thursday of month)."""
    expiries = []
    today = date.today()
    year, month = today.year, today.month
    for _ in range(n + 2):
        if month > 12:
            month = 1
            year += 1
        cal = calendar.monthcalendar(year, month)
        thursdays = [week[3] for week in cal if week[3] != 0]
        last_thursday = date(year, month, thursdays[-1])
        if last_thursday >= today:
            expiries.append(last_thursday.strftime("%d %b %Y"))
        month += 1
        if len(expiries) >= n:
            break
    return expiries


def get_strike_range(spot_price: float, step: int = 50, count: int = 20) -> list[int]:
    """Generate strike prices around spot."""
    atm = round(spot_price / step) * step
    strikes = [atm + (i - count // 2) * step for i in range(count)]
    return sorted(strikes)


def get_live_price(symbol: str, exchange: str = "NSE") -> float | None:
    try:
        quote = kd.kite_client().quote(f"{exchange}:{symbol}")
        return quote[f"{exchange}:{symbol}"]["last_price"]
    except Exception:
        return None


def get_option_price(underlying: str, expiry_str: str, strike: int, opt_type: str) -> float | None:
    """Fetch live option price from Kite.

    Kite uses two symbol formats:
      Monthly expiry  →  NIFTY25APR24500CE
      Weekly expiry   →  NIFTY2541724500CE  (YY + single month code + DD)
    """
    try:
        exchange = INDICES.get(underlying, {}).get("exchange", "NFO")
        dt = datetime.strptime(expiry_str, "%d %b %Y")

        # Check if this expiry is the last Thursday of the month (monthly) or not (weekly)
        cal = calendar.monthcalendar(dt.year, dt.month)
        thursdays = [week[3] for week in cal if week[3] != 0]
        last_thu = date(dt.year, dt.month, thursdays[-1])

        if dt.date() == last_thu:
            # Monthly format — e.g. 25APR
            exp_fmt = dt.strftime("%y%b").upper()
        else:
            # Weekly format — Kite uses single char for Oct=O, Nov=N, Dec=D
            month_code = {
                1: "1", 2: "2", 3: "3", 4: "4",
                5: "5", 6: "6", 7: "7", 8: "8",
                9: "9", 10: "O", 11: "N", 12: "D",
            }
            exp_fmt = dt.strftime("%y") + month_code[dt.month] + dt.strftime("%d")

        symbol = f"{underlying}{exp_fmt}{strike}{opt_type}"
        quote = kd.kite_client().quote(f"{exchange}:{symbol}")
        return quote[f"{exchange}:{symbol}"]["last_price"]
    except Exception:
        return None


def place_fo_order(
    instrument_type: str,
    underlying: str,
    expiry: str,
    strike: int,
    opt_type: str,
    lots: int,
    action: str,
    price: float,
    lot_size: int,
) -> dict:
    portfolio = load_fo_portfolio()

    qty = lots * lot_size
    total_value = price * qty
    position_key = f"{underlying}_{expiry}_{strike}_{opt_type}"

    if action == "BUY":
        if portfolio["cash"] < total_value:
            return {"error": f"Insufficient funds! Need ₹{total_value:,.2f}, have ₹{portfolio['cash']:,.2f}"}
        portfolio["cash"] -= total_value
        positions = portfolio["positions"]
        if position_key in positions:
            existing = positions[position_key]
            new_lots = existing["lots"] + lots
            new_avg = ((existing["avg_price"] * existing["lots"]) + (price * lots)) / new_lots
            positions[position_key].update({"lots": new_lots, "avg_price": new_avg})
        else:
            positions[position_key] = {
                "underlying": underlying,
                "expiry": expiry,
                "strike": strike,
                "opt_type": opt_type,
                "lots": lots,
                "lot_size": lot_size,
                "avg_price": price,
                "instrument_type": instrument_type,
            }

    elif action == "SELL":
        positions = portfolio["positions"]
        if position_key not in positions or positions[position_key]["lots"] < lots:
            held = positions.get(position_key, {}).get("lots", 0)
            return {"error": f"Insufficient position! You hold {held} lots of {underlying} {strike} {opt_type}"}
        portfolio["cash"] += total_value
        positions[position_key]["lots"] -= lots
        if positions[position_key]["lots"] == 0:
            del positions[position_key]

    # Save portfolio atomically to SQLite
    save_fo_portfolio(portfolio)

    # Append trade record to SQLite (crash-safe)
    store.append_fo_trade({
        "action":     action,
        "underlying": underlying,
        "symbol":     f"{underlying}_{strike}_{opt_type}",
        "expiry":     expiry,
        "strike":     strike,
        "opt_type":   opt_type,
        "lots":       lots,
        "lot_size":   lot_size,
        "qty":        qty,
        "price":      price,
        "premium":    total_value,
        "trade_type": "paper",
        "traded_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    trade = {
        "action": action, "underlying": underlying, "expiry": expiry,
        "strike": strike, "opt_type": opt_type, "lots": lots,
        "lot_size": lot_size, "qty": qty, "price": price, "total": total_value,
    }
    return {"success": trade}


# ── Alert Engine ───────────────────────────────────────────────────────────

def get_current_pnl() -> float:
    """Calculate total unrealized P&L across all open positions."""
    portfolio = load_fo_portfolio()
    positions = portfolio["positions"]
    total_pnl = 0.0
    for key, pos in positions.items():
        current_price = get_option_price(
            pos["underlying"], pos["expiry"], pos["strike"], pos["opt_type"]
        ) or pos["avg_price"]
        qty = pos["lots"] * pos["lot_size"]
        total_pnl += (current_price - pos["avg_price"]) * qty
    return total_pnl


def run_alert_checks() -> None:
    """Check all active alerts and send Telegram if any condition is met."""
    token = store.get_setting("telegram_token")
    chat_id = store.get_setting("telegram_chat_id")
    if not token or not chat_id:
        return  # Telegram not configured yet

    active_alerts = store.load_active_alerts()
    if not active_alerts:
        return

    triggered_ids = []

    for alert in active_alerts:
        try:
            if alert["alert_type"] == "PRICE":
                current_price = get_live_price(alert["symbol"], alert["exchange"])
                if current_price and ae.check_condition(current_price, alert["condition"], alert["target_value"]):
                    msg = ae.format_price_alert_message(
                        alert["display_name"], alert["condition"],
                        alert["target_value"], current_price,
                    )
                    ae.send_telegram_message(token, chat_id, msg)
                    triggered_ids.append(alert["id"])

            elif alert["alert_type"] == "PNL":
                current_pnl = get_current_pnl()
                if ae.check_condition(current_pnl, alert["condition"], alert["target_value"]):
                    msg = ae.format_pnl_alert_message(
                        alert["condition"], alert["target_value"], current_pnl,
                    )
                    ae.send_telegram_message(token, chat_id, msg)
                    triggered_ids.append(alert["id"])
        except Exception:
            continue

    for alert_id in triggered_ids:
        store.mark_alert_triggered(alert_id)


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("💰 F&O Portfolio")
    portfolio = load_fo_portfolio()
    st.metric("Available Capital", f"₹ {portfolio['cash']:,.2f}")
    st.divider()

    if st.button("🔄 Reset F&O Portfolio", use_container_width=True):
        store.reset_fo_portfolio(starting_capital=STARTING_CAPITAL)
        store.clear_fo_trades()
        st.success(f"Reset to ₹{STARTING_CAPITAL:,.0f}!")
        st.rerun()

    auto_refresh = st.toggle("Auto Refresh (5s)", value=False)
    if auto_refresh:
        st.caption("⚡ Auto refreshing every 5s")
        time.sleep(5)
        st.rerun()

    auth.render_sidebar_kite_session(key_prefix="fo")
    auth.render_logout_controls(key="kite_logout_fo")

if not auth.ensure_kite_ready():
    st.stop()

# Run alert checks on every page load
run_alert_checks()

# ── Header ─────────────────────────────────────────────────────────────────
st.title("📊 F&O Paper Trading")
st.caption(f"Simulate Index & Stock Options trading. Starting capital: ₹{STARTING_CAPITAL:,.0f}")

# ── Tabs ───────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Place Order",
    "💼 Open Positions",
    "📋 Trade History",
    "📊 P&L Summary",
    "🔔 Alerts",
])

with tab1:
    st.subheader("Place F&O Order")

    inst_type = st.radio("Instrument Type", ["Index Options", "Stock Options"], horizontal=True)

    col1, col2 = st.columns(2)

    with col1:
        if inst_type == "Index Options":
            underlying = st.selectbox("Select Index", list(INDICES.keys()))
            lot_size = INDICES[underlying]["lot"]
            st.caption(f"Lot size: **{lot_size}**")

            spot_exchange = INDEX_SPOT_EXCHANGE[underlying]
            spot_price = get_live_price(INDICES[underlying]["symbol"], spot_exchange) or 24000.0
        else:
            underlying = st.selectbox("Select Stock", FO_STOCKS)
            lot_size = FO_STOCKS_LOT.get(underlying, 500)
            st.caption(f"Lot size: **{lot_size}**")
            spot_price = get_live_price(underlying, "NSE") or 1000.0

        if spot_price:
            st.success(f"📡 Spot Price: ₹ {spot_price:,.2f}")

    with col2:
        expiry_type = st.radio("Expiry Type", ["Weekly", "Monthly"], horizontal=True)
        if expiry_type == "Weekly":
            expiries = get_weekly_expiries(5)
        else:
            expiries = get_monthly_expiries(3)
        expiry = st.selectbox("Select Expiry", expiries)
        opt_type = st.radio("Option Type", ["CE", "PE"], horizontal=True)

    # SENSEX uses 100-point strike steps, not 50
    step = 100 if underlying in ["BANKNIFTY", "SENSEX"] else 50
    strikes = get_strike_range(spot_price, step=step, count=30)
    atm = round(spot_price / step) * step

    strike = st.select_slider("Strike Price", options=strikes, value=atm)

    diff = strike - atm
    if diff == 0:
        moneyness = "🎯 ATM (At The Money)"
    elif (opt_type == "CE" and diff < 0) or (opt_type == "PE" and diff > 0):
        moneyness = f"💚 ITM (In The Money) by {abs(diff)}"
    else:
        moneyness = f"🔴 OTM (Out of The Money) by {abs(diff)}"
    st.caption(moneyness)

    option_price = get_option_price(underlying, expiry, strike, opt_type)

    col3, col4 = st.columns(2)
    with col3:
        if option_price:
            st.success(f"📡 Option Price: ₹ {option_price:,.2f}")
        else:
            st.warning("⚠️ Live price unavailable — enter manually")
            option_price = st.number_input("Option Premium (₹)", min_value=0.05, value=100.0, step=0.05)

    with col4:
        lots = st.number_input("Number of Lots", min_value=1, value=1, step=1)
        total_qty = lots * lot_size
        total_cost = option_price * total_qty
        st.info(f"Qty: {total_qty} | Total: ₹ {total_cost:,.2f}")

    action = st.radio("Action", ["BUY", "SELL"], horizontal=True)

    btn_label = f"{'🟢 BUY' if action == 'BUY' else '🔴 SELL'} {underlying} {strike} {opt_type} ({expiry})"
    if st.button(btn_label, type="primary", use_container_width=True):
        result = place_fo_order(
            instrument_type=inst_type,
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            opt_type=opt_type,
            lots=lots,
            action=action,
            price=option_price,
            lot_size=lot_size,
        )
        if "error" in result:
            st.error(result["error"])
        else:
            t = result["success"]
            st.success(
                f"✅ {t['action']} {t['lots']} lot(s) of {t['underlying']} {t['strike']} {t['opt_type']} "
                f"@ ₹{t['price']:,.2f} | Total: ₹{t['total']:,.2f}"
            )
            st.rerun()


with tab2:
    st.subheader("💼 Open Positions")
    portfolio = load_fo_portfolio()
    positions = portfolio["positions"]

    if positions:
        rows = []
        total_invested = 0
        total_current = 0

        for key, pos in positions.items():
            current_price = get_option_price(
                pos["underlying"], pos["expiry"], pos["strike"], pos["opt_type"]
            ) or pos["avg_price"]

            qty = pos["lots"] * pos["lot_size"]
            invested = pos["avg_price"] * qty
            current = current_price * qty
            pnl = current - invested
            pnl_pct = (pnl / invested) * 100 if invested else 0
            total_invested += invested
            total_current += current

            rows.append({
                "Underlying": pos["underlying"],
                "Expiry": pos["expiry"],
                "Strike": pos["strike"],
                "Type": pos["opt_type"],
                "Lots": pos["lots"],
                "Qty": qty,
                "Avg Price": f"₹ {pos['avg_price']:,.2f}",
                "Current Price": f"₹ {current_price:,.2f}",
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
            st.metric("Premium Paid", f"₹ {total_invested:,.2f}")
        with c3:
            st.metric("Current Value", f"₹ {total_current:,.2f}")
        with c4:
            st.metric("Unrealized P&L", f"₹ {total_pnl:,.2f}", delta=f"{total_pnl_pct:.2f}%")

        st.metric("💰 Net Worth", f"₹ {net_worth:,.2f}",
                  delta=f"₹ {net_worth - STARTING_CAPITAL:,.2f} from ₹{STARTING_CAPITAL:,.0f}")
    else:
        st.info("No open positions. Place your first F&O order! 👆")


with tab3:
    st.subheader("📋 Trade History")
    trades = load_fo_trades()

    if trades:
        tdf = pd.DataFrame(trades)
        display_cols = {
            "id": "#", "traded_at": "Time", "underlying": "Underlying",
            "expiry": "Expiry", "strike": "Strike", "opt_type": "Type",
            "action": "Action", "lots": "Lots", "price": "Price", "premium": "Total"
        }
        tdf = tdf[[c for c in display_cols if c in tdf.columns]]
        tdf = tdf.rename(columns=display_cols)
        if "Price" in tdf.columns:
            tdf["Price"] = tdf["Price"].apply(lambda x: f"₹ {x:,.2f}")
        if "Total" in tdf.columns:
            tdf["Total"] = tdf["Total"].apply(lambda x: f"₹ {x:,.2f}")
        st.dataframe(tdf, use_container_width=True, hide_index=True, height=400)

        if st.button("🗑️ Clear Trade History"):
            store.clear_fo_trades()
            st.success("Cleared!")
            st.rerun()
    else:
        st.info("No trades yet. Start trading! 🚀")


with tab4:
    st.subheader("📊 P&L Summary")
    trades = load_fo_trades()

    if trades:
        df = pd.DataFrame(trades)

        st.markdown("#### By Underlying")
        summary = df.groupby(["underlying", "opt_type"]).agg(
            Total_Trades=("id", "count"),
            Buy_Trades=("action", lambda x: (x == "BUY").sum()),
            Sell_Trades=("action", lambda x: (x == "SELL").sum()),
            Total_Lots=("lots", "sum"),
            Total_Premium=("premium", "sum"),
        ).reset_index()
        st.dataframe(summary, use_container_width=True, hide_index=True)

        st.markdown("#### By Date")
        df["date"] = pd.to_datetime(df["traded_at"]).dt.date
        daily = df.groupby("date").agg(
            Trades=("id", "count"),
            Total_Premium=("premium", "sum"),
        ).reset_index()
        daily["Total_Premium"] = daily["Total_Premium"].apply(lambda x: f"₹ {x:,.2f}")
        st.dataframe(daily, use_container_width=True, hide_index=True)
    else:
        st.info("No trades to summarize yet!")


# ── Tab 5: Alerts ──────────────────────────────────────────────────────────
with tab5:
    st.subheader("🔔 Alerts")

    # ── Telegram Setup ─────────────────────────────────────────────────────
    with st.expander("⚙️ Telegram Setup", expanded=not bool(store.get_setting("telegram_token"))):
        st.markdown(
            "**How to get your Bot Token and Chat ID:**\n"
            "1. Open Telegram → search **@BotFather** → send `/newbot`\n"
            "2. Follow the steps → BotFather gives you a **Bot Token**\n"
            "3. Send any message to your new bot\n"
            "4. Open this URL in browser to get your Chat ID:\n"
            "   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`\n"
            "5. Look for `\"id\"` inside `\"chat\"` — that's your Chat ID"
        )
        saved_token = store.get_setting("telegram_token") or ""
        saved_chat  = store.get_setting("telegram_chat_id") or ""

        tg_token = st.text_input("Bot Token", value=saved_token, type="password", placeholder="123456789:ABCdef...")
        tg_chat  = st.text_input("Chat ID",   value=saved_chat,  placeholder="e.g. 987654321")

        col_save, col_test = st.columns(2)
        with col_save:
            if st.button("💾 Save Telegram Config", use_container_width=True):
                if tg_token.strip() and tg_chat.strip():
                    store.set_setting("telegram_token", tg_token.strip())
                    store.set_setting("telegram_chat_id", tg_chat.strip())
                    st.success("Saved!")
                else:
                    st.error("Both Token and Chat ID are required.")
        with col_test:
            if st.button("📨 Send Test Message", use_container_width=True):
                if tg_token.strip() and tg_chat.strip():
                    ok, msg = ae.test_telegram_connection(tg_token.strip(), tg_chat.strip())
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("Enter Token and Chat ID first.")

    st.divider()

    # ── Add New Alert ──────────────────────────────────────────────────────
    st.markdown("### ➕ Add New Alert")

    alert_type = st.radio("Alert Type", ["📈 Price Alert", "💰 P&L Alert"], horizontal=True)

    if alert_type == "📈 Price Alert":
        col_a, col_b = st.columns(2)
        with col_a:
            symbol_category = st.radio("Symbol Type", ["Index", "Stock"], horizontal=True)

            if symbol_category == "Index":
                selected_name = st.selectbox("Select Index", list(INDICES.keys()), key="alert_index")
                api_symbol  = INDICES[selected_name]["symbol"]
                api_exchange = INDEX_SPOT_EXCHANGE[selected_name]
                current_spot = get_live_price(api_symbol, api_exchange) or 0.0
            else:
                selected_name = st.selectbox("Select Stock", FO_STOCKS, key="alert_stock")
                api_symbol   = selected_name
                api_exchange = "NSE"
                current_spot = get_live_price(api_symbol, api_exchange) or 0.0

            if current_spot:
                st.info(f"📡 Current Price: ₹ {current_spot:,.2f}")

        with col_b:
            price_condition = st.radio("Condition", ["ABOVE", "BELOW"], horizontal=True, key="price_cond")
            target_price = st.number_input(
                "Target Price (₹)",
                min_value=0.01,
                value=float(round(current_spot * 1.01)) if current_spot else 100.0,
                step=10.0,
                key="target_price",
            )

        if st.button("🔔 Add Price Alert", type="primary", use_container_width=True):
            if not store.get_setting("telegram_token"):
                st.error("⚠️ Please configure Telegram first (expand setup above).")
            else:
                store.create_alert(
                    alert_type="PRICE",
                    display_name=selected_name,
                    symbol=api_symbol,
                    exchange=api_exchange,
                    condition=price_condition,
                    target_value=target_price,
                )
                st.success(
                    f"✅ Alert set: {selected_name} {price_condition} ₹{target_price:,.2f}"
                )
                st.rerun()

    else:  # P&L Alert
        col_a, col_b = st.columns(2)
        with col_a:
            pnl_condition = st.radio("Condition", ["ABOVE", "BELOW"], horizontal=True, key="pnl_cond")
        with col_b:
            current_pnl = get_current_pnl()
            st.info(f"Current P&L: ₹ {current_pnl:,.2f}")
            target_pnl = st.number_input(
                "Target P&L (₹)",
                value=5000.0,
                step=500.0,
                key="target_pnl",
            )

        if st.button("🔔 Add P&L Alert", type="primary", use_container_width=True):
            if not store.get_setting("telegram_token"):
                st.error("⚠️ Please configure Telegram first (expand setup above).")
            else:
                store.create_alert(
                    alert_type="PNL",
                    display_name="Portfolio P&L",
                    symbol=None,
                    exchange=None,
                    condition=pnl_condition,
                    target_value=target_pnl,
                )
                st.success(
                    f"✅ P&L Alert set: P&L {pnl_condition} ₹{target_pnl:,.2f}"
                )
                st.rerun()

    st.divider()

    # ── Active Alerts ──────────────────────────────────────────────────────
    st.markdown("### 📋 Active Alerts")
    active_alerts = store.load_active_alerts()

    if active_alerts:
        for alert in active_alerts:
            col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])
            with col1:
                st.write(f"**{alert['display_name']}**")
            with col2:
                badge = "📈 Price" if alert["alert_type"] == "PRICE" else "💰 P&L"
                st.write(badge)
            with col3:
                direction = "🔼" if alert["condition"] == "ABOVE" else "🔽"
                st.write(f"{direction} {alert['condition']} ₹{alert['target_value']:,.2f}")
            with col4:
                st.write(alert["created_at"][:16].replace("T", " "))
            with col5:
                if st.button("🗑️", key=f"del_alert_{alert['id']}"):
                    store.delete_alert(alert["id"])
                    st.rerun()
    else:
        st.info("No active alerts. Add one above! 👆")

    st.divider()

    # ── Triggered Alerts History ───────────────────────────────────────────
    st.markdown("### ✅ Triggered Alerts History")
    all_alerts = store.load_all_alerts()
    triggered = [a for a in all_alerts if a["status"] == "TRIGGERED"]

    if triggered:
        tdf = pd.DataFrame(triggered)
        tdf = tdf[["display_name", "alert_type", "condition", "target_value", "created_at", "triggered_at"]]
        tdf.columns = ["Symbol", "Type", "Condition", "Target ₹", "Created", "Triggered At"]
        tdf["Target ₹"] = tdf["Target ₹"].apply(lambda x: f"₹ {x:,.2f}")
        tdf["Created"]      = tdf["Created"].str[:16].str.replace("T", " ")
        tdf["Triggered At"] = tdf["Triggered At"].str[:16].str.replace("T", " ")
        st.dataframe(tdf, use_container_width=True, hide_index=True)

        if st.button("🗑️ Clear Triggered History"):
            store.clear_triggered_alerts()
            st.success("Cleared!")
            st.rerun()
    else:
        st.info("No alerts have been triggered yet.")
