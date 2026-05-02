"""F&O Paper Trading — simulate options/futures trading with real Kite prices.

WHY THIS FILE EXISTS:
    Lets you practice F&O trading using REAL live prices from Kite,
    but with fake money — so you can learn without losing real capital.
    Tracks your paper positions, P&L, and trade history in JSON files.
"""

from __future__ import annotations

import calendar
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
import streamlit as st

import kite_data as kd
import auth_streamlit as auth

# ── Logging setup ──────────────────────────────────────────────────────────
# WHY: Instead of silent failures, we log errors to a file so you can debug
# problems even after they happen. Check fo_paper_trading.log if something
# goes wrong and you're not sure why.
logging.basicConfig(
    filename="fo_paper_trading.log",
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="F&O Paper Trading",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

auth.render_auth_cleared_banner()

# ── Constants ──────────────────────────────────────────────────────────────

INDICES = {
    "NIFTY":      {"lot": 50,  "exchange": "NFO"},
    "BANKNIFTY":  {"lot": 15,  "exchange": "NFO"},
    "FINNIFTY":   {"lot": 40,  "exchange": "NFO"},
    "MIDCPNIFTY": {"lot": 75,  "exchange": "NFO"},
    "SENSEX":     {"lot": 10,  "exchange": "BFO"},
}

# WHY: Kite uses different symbol names for indices than what you see on screen.
# For example, to get the NIFTY 50 price, Kite wants "NSE:NIFTY 50" not "NSE:NIFTY".
INDEX_SPOT_MAP = {
    "NIFTY":      ("NIFTY 50",          "NSE"),
    "BANKNIFTY":  ("NIFTY BANK",        "NSE"),
    "FINNIFTY":   ("NIFTY FIN SERVICE", "NSE"),
    "MIDCPNIFTY": ("NIFTY MID SELECT",  "NSE"),
    "SENSEX":     ("SENSEX",            "BSE"),
}

# WHY: yfinance uses Yahoo Finance tickers — needed as a fallback when Kite is down.
INDEX_YFINANCE_MAP = {
    "NIFTY":      "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "^NSMIDCP",
    "SENSEX":     "^BSESN",
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

# WHY: F&O lot sizes are fixed by NSE — you can't trade partial lots.
# Each stock has a minimum contract size. Wrong lot size = wrong P&L calculations.
FO_STOCKS_LOT = {s: 500 for s in FO_STOCKS}
FO_STOCKS_LOT.update({
    "MRF": 10, "PAGEIND": 15, "BOSCHLTD": 25, "EICHERMOT": 50,
    "MARUTI": 25, "NESTLEIND": 50, "TITAN": 175, "RELIANCE": 250,
    "TCS": 150, "INFY": 300, "HDFCBANK": 550, "ICICIBANK": 700,
})

# ── Storage ────────────────────────────────────────────────────────────────
FO_TRADES_FILE    = Path("fo_paper_trades.json")
FO_PORTFOLIO_FILE = Path("fo_paper_portfolio.json")
STARTING_CAPITAL  = 500_000.0  # ₹5,00,000


# ══════════════════════════════════════════════════════════════════════════
# SAFE FILE I/O
# WHY: JSON files can get corrupted if the app crashes mid-write (power cut,
# force-quit, disk full). These functions safely handle that instead of crashing
# with a confusing Python error.
# ══════════════════════════════════════════════════════════════════════════

def load_fo_trades() -> list:
    """Load trade history. Returns empty list if file is missing or corrupted."""
    if not FO_TRADES_FILE.exists():
        return []
    try:
        return json.loads(FO_TRADES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Could not read trades file: {e}")
        st.warning("⚠️ Trade history file seems corrupted. Starting fresh.")
        return []


def save_fo_trades(trades: list) -> None:
    """Save trade history. Shows error if disk write fails."""
    try:
        FO_TRADES_FILE.write_text(json.dumps(trades, indent=2), encoding="utf-8")
    except OSError as e:
        logger.error(f"Could not save trades: {e}")
        st.error("❌ Could not save trade history. Check if disk has space.")


def load_fo_portfolio() -> dict:
    """Load portfolio. Returns fresh portfolio if file is missing or corrupted."""
    if not FO_PORTFOLIO_FILE.exists():
        return {"cash": STARTING_CAPITAL, "positions": {}}
    try:
        data = json.loads(FO_PORTFOLIO_FILE.read_text(encoding="utf-8"))
        # WHY: Validate keys exist — file could be from an older version of the app
        if "cash" not in data or "positions" not in data:
            raise ValueError("Portfolio file is missing required keys")
        return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.error(f"Could not read portfolio file: {e}")
        st.warning("⚠️ Portfolio file seems corrupted. Starting with a fresh portfolio.")
        return {"cash": STARTING_CAPITAL, "positions": {}}


def save_fo_portfolio(portfolio: dict) -> None:
    """Save portfolio. Shows error if disk write fails."""
    try:
        FO_PORTFOLIO_FILE.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")
    except OSError as e:
        logger.error(f"Could not save portfolio: {e}")
        st.error("❌ Could not save portfolio. Check if disk has space.")


# ══════════════════════════════════════════════════════════════════════════
# EXPIRY HELPERS
# ══════════════════════════════════════════════════════════════════════════

def get_weekly_expiries(n: int = 5) -> list[str]:
    """Get next N weekly expiries. In India, F&O expires every Thursday."""
    expiries, d = [], date.today()
    while len(expiries) < n:
        if d.weekday() == 3:  # 3 = Thursday
            expiries.append(d.strftime("%d %b %Y"))
        d += timedelta(days=1)
    return expiries


def get_monthly_expiries(n: int = 3) -> list[str]:
    """Get next N monthly expiries (last Thursday of each month)."""
    expiries = []
    today = date.today()
    year, month = today.year, today.month
    for _ in range(n + 3):
        if month > 12:
            month, year = 1, year + 1
        cal = calendar.monthcalendar(year, month)
        thursdays = [week[3] for week in cal if week[3] != 0]
        last_thu = date(year, month, thursdays[-1])
        if last_thu >= today:
            expiries.append(last_thu.strftime("%d %b %Y"))
        month += 1
        if len(expiries) >= n:
            break
    return expiries


def get_strike_range(spot_price: float, step: int = 50, count: int = 30) -> list[int]:
    """Generate strike prices centered around the current spot price."""
    atm = round(spot_price / step) * step
    return sorted([atm + (i - count // 2) * step for i in range(count)])


def days_to_expiry(expiry_str: str) -> int:
    """How many calendar days until this option expires."""
    try:
        exp = datetime.strptime(expiry_str, "%d %b %Y").date()
        return (exp - date.today()).days
    except ValueError:
        return 999  # unknown expiry — assume far away


# ══════════════════════════════════════════════════════════════════════════
# PRICE FETCHING WITH SMART FALLBACKS
#
# WHY we have 3 layers of handling:
#   1. Kite API (real-time, best)     → try this first
#   2. yfinance fallback (15-min delay) → if Kite fails for non-auth reasons
#   3. Manual entry                   → if both fail
#
# WHY we distinguish AUTH errors from other errors:
#   - Auth error = token expired → user MUST re-login, no point trying yfinance
#   - Other errors = API down, bad symbol, network issue → yfinance might work
# ══════════════════════════════════════════════════════════════════════════

def get_live_price(symbol: str, exchange: str = "NSE") -> tuple[float | None, str]:
    """
    Fetch live spot price from Kite. Falls back to yfinance if Kite is unavailable.

    Returns:
        (price, source) — source is "kite", "yfinance", "auth_error", or "unavailable"
    """
    kite_key = f"{exchange}:{symbol}"
    try:
        quote = kd.kite_client().quote(kite_key)
        price = quote[kite_key]["last_price"]
        if price and price > 0:
            return price, "kite"
        # WHY: Kite sometimes returns 0 for illiquid/halted symbols — not useful
        raise ValueError(f"Kite returned zero/null price for {kite_key}")

    except Exception as e:
        if kd.is_kite_auth_error(e):
            # WHY: Token expired — yfinance won't help, user needs to re-login
            logger.error(f"Kite auth error for {kite_key}: {e}")
            return None, "auth_error"

        logger.error(f"Kite spot fetch failed ({kite_key}): {e}")

        # ── yfinance fallback ──────────────────────────────────────────────
        # WHY: Find matching yfinance ticker — only works for indices + NSE stocks
        yf_ticker = None
        for idx_name, (spot_sym, spot_exch) in INDEX_SPOT_MAP.items():
            if spot_sym == symbol and spot_exch == exchange:
                yf_ticker = INDEX_YFINANCE_MAP.get(idx_name)
                break
        if yf_ticker is None and exchange == "NSE":
            yf_ticker = f"{symbol}.NS"  # NSE stock format for Yahoo Finance

        if yf_ticker:
            try:
                hist = yf.Ticker(yf_ticker).history(period="2d")
                if not hist.empty:
                    return float(hist["Close"].iloc[-1]), "yfinance"
            except Exception as yf_err:
                logger.error(f"yfinance fallback failed ({yf_ticker}): {yf_err}")

        return None, "unavailable"


def get_option_price(
    underlying: str, expiry_str: str, strike: int, opt_type: str
) -> tuple[float | None, str]:
    """
    Fetch live option premium from Kite NFO.

    WHY the symbol format is tricky:
        Kite NFO symbols look like: NIFTY24APR24000CE
        - NIFTY  = underlying name
        - 24APR  = YY + first 3 letters of month in UPPERCASE (e.g. APR, MAY, JUN)
        - 24000  = strike price (no decimals)
        - CE/PE  = Call or Put
        If ANY part is wrong, Kite returns "No instrument found" error.

    Returns:
        (price, source) — source is "kite", "auth_error", "bad_symbol",
                          "zero_price", or "unavailable"
    """
    try:
        dt = datetime.strptime(expiry_str, "%d %b %Y")
        # WHY: [:5] trims to exactly "YYMMM" e.g. "24APR" — Kite is very strict
        exp_fmt    = dt.strftime("%y%b").upper()[:5]
        nfo_symbol = f"{underlying}{exp_fmt}{strike}{opt_type}"
        kite_key   = f"NFO:{nfo_symbol}"

        quote = kd.kite_client().quote(kite_key)
        price = quote[kite_key]["last_price"]

        if price and price > 0:
            return price, "kite"
        # WHY: Zero price = option not yet traded today or deeply OTM with no buyers
        return None, "zero_price"

    except Exception as e:
        if kd.is_kite_auth_error(e):
            logger.error(f"Kite auth error fetching option: {e}")
            return None, "auth_error"

        err_lower = str(e).lower()
        # WHY: "No instrument" = wrong symbol format or that contract doesn't exist in NFO
        if "no instrument" in err_lower or "invalid" in err_lower:
            logger.warning(
                f"Option symbol not found in NFO: "
                f"{underlying} {expiry_str} {strike} {opt_type}"
            )
            return None, "bad_symbol"

        logger.error(
            f"Option price fetch failed "
            f"({underlying} {strike} {opt_type} {expiry_str}): {e}"
        )
        return None, "unavailable"


def render_price_badge(price: float | None, source: str, label: str = "Price") -> float | None:
    """
    Show a colored status badge explaining where the price came from.
    WHY: You should always know if you're looking at real-time or delayed data.
    Returns the price if valid, None if not usable.
    """
    if price and source == "kite":
        st.success(f"📡 **{label}:** ₹ {price:,.2f}  *(Live — Kite)*")
        return price
    elif price and source == "yfinance":
        st.warning(f"⏱️ **{label}:** ₹ {price:,.2f}  *(~15 min delayed — Yahoo Finance fallback)*")
        return price
    elif source == "auth_error":
        st.error("🔐 **Kite session expired.** Please re-login using the sidebar → *Kite session (sign in / renew)*.")
        return None
    elif source == "bad_symbol":
        st.warning("⚠️ This option contract was **not found in NFO**. Enter the premium manually below.")
        return None
    elif source == "zero_price":
        st.warning("⚠️ Option returned ₹ 0 — it may not have traded yet today. Enter manually.")
        return None
    else:
        st.warning(f"⚠️ **{label}** could not be fetched (Kite + Yahoo both failed). Enter manually.")
        return None


# ══════════════════════════════════════════════════════════════════════════
# ORDER PLACEMENT WITH FULL VALIDATION
# ══════════════════════════════════════════════════════════════════════════

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
    """
    Place a paper F&O order. Validates everything before touching the portfolio.

    WHY we validate so much:
        - price ≤ 0   → something went wrong fetching price, don't trade on bad data
        - lots ≤ 0    → would silently corrupt portfolio math
        - expired     → trading expired options produces meaningless P&L
        - sell > held → would create negative positions which break P&L calculations
    """

    # ── Validation ─────────────────────────────────────────────────────────
    if price <= 0:
        return {"error": f"Invalid price ₹{price:.2f}. Price must be greater than zero."}
    if lots <= 0:
        return {"error": "Number of lots must be at least 1."}
    if lot_size <= 0:
        return {"error": f"Invalid lot size: {lot_size}. This is a data error, please report it."}

    # WHY: Trading an already-expired option is meaningless and would show wrong P&L
    dte = days_to_expiry(expiry)
    if dte < 0:
        return {"error": f"This option expired **{abs(dte)} day(s) ago**. Please select a valid expiry date."}

    portfolio    = load_fo_portfolio()
    trades       = load_fo_trades()
    qty          = lots * lot_size
    total_value  = price * qty
    position_key = f"{underlying}_{expiry}_{strike}_{opt_type}"

    if action == "BUY":
        # WHY: Can't buy what you can't afford — prevent portfolio going negative
        if portfolio["cash"] < total_value:
            shortfall = total_value - portfolio["cash"]
            return {
                "error": (
                    f"Insufficient funds!\n\n"
                    f"**Need:** ₹{total_value:,.2f}  |  "
                    f"**Have:** ₹{portfolio['cash']:,.2f}  |  "
                    f"**Short by:** ₹{shortfall:,.2f}"
                )
            }
        portfolio["cash"] -= total_value
        positions = portfolio["positions"]

        if position_key in positions:
            # WHY: Correct average price formula when adding to an existing position
            existing = positions[position_key]
            new_lots = existing["lots"] + lots
            new_avg  = (
                (existing["avg_price"] * existing["lots"]) + (price * lots)
            ) / new_lots
            positions[position_key].update({
                "lots":      new_lots,
                "avg_price": round(new_avg, 4),
            })
        else:
            positions[position_key] = {
                "underlying":      underlying,
                "expiry":          expiry,
                "strike":          strike,
                "opt_type":        opt_type,
                "lots":            lots,
                "lot_size":        lot_size,
                "avg_price":       price,
                "instrument_type": instrument_type,
                "entry_time":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    elif action == "SELL":
        positions = portfolio["positions"]
        held_lots = positions.get(position_key, {}).get("lots", 0)

        # WHY: Can't sell more than you hold — prevents negative lot counts
        if position_key not in positions or held_lots < lots:
            return {
                "error": (
                    f"Cannot sell **{lots} lot(s)** — you only hold "
                    f"**{held_lots} lot(s)** of {underlying} {strike} {opt_type}."
                )
            }
        portfolio["cash"] += total_value
        positions[position_key]["lots"] -= lots
        if positions[position_key]["lots"] == 0:
            del positions[position_key]  # WHY: Remove fully closed positions

    else:
        return {"error": f"Unknown action '{action}'. Must be BUY or SELL."}

    trade = {
        "id":              len(trades) + 1,
        "timestamp":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instrument_type": instrument_type,
        "underlying":      underlying,
        "expiry":          expiry,
        "strike":          strike,
        "opt_type":        opt_type,
        "action":          action,
        "lots":            lots,
        "lot_size":        lot_size,
        "qty":             qty,
        "price":           price,
        "total":           total_value,
    }
    trades.append(trade)
    save_fo_trades(trades)
    save_fo_portfolio(portfolio)
    return {"success": trade}


# ══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.subheader("💰 F&O Portfolio")
    _p = load_fo_portfolio()
    st.metric("Available Capital", f"₹ {_p['cash']:,.2f}")
    st.caption(f"Open positions: **{len(_p.get('positions', {}))}**")
    st.divider()

    # WHY: Confirm before reset — prevents accidental wipe of all paper trades
    if st.button("🔄 Reset F&O Portfolio", width="stretch"):
        st.session_state["confirm_reset_fo"] = True

    if st.session_state.get("confirm_reset_fo"):
        st.warning("⚠️ This will delete ALL paper trades and reset capital!")
        cy, cn = st.columns(2)
        with cy:
            if st.button("✅ Yes, Reset", width="stretch", key="reset_yes"):
                save_fo_portfolio({"cash": STARTING_CAPITAL, "positions": {}})
                save_fo_trades([])
                st.session_state.pop("confirm_reset_fo", None)
                st.success(f"Reset to ₹{STARTING_CAPITAL:,.0f}!")
                st.rerun()
        with cn:
            if st.button("❌ Cancel", width="stretch", key="reset_no"):
                st.session_state.pop("confirm_reset_fo", None)
                st.rerun()

    auth.render_sidebar_kite_session(key_prefix="fo")
    auth.render_logout_controls(key="kite_logout_fo")

# WHY: Stop here if not logged in — everything below needs Kite access
if not auth.ensure_kite_ready():
    st.stop()

# ── Header ─────────────────────────────────────────────────────────────────
st.title("📊 F&O Paper Trading")
st.caption(f"Simulate Index & Stock Options with real Kite prices. Starting capital: ₹{STARTING_CAPITAL:,.0f}")

tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Place Order",
    "💼 Open Positions",
    "📋 Trade History",
    "📊 P&L Summary",
])


# ══════════════════════════════════════════════════════════════════════════
# TAB 1 — PLACE ORDER
# ══════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Place F&O Order")

    inst_type = st.radio("Instrument Type", ["Index Options", "Stock Options"], horizontal=True)

    col1, col2 = st.columns(2)

    with col1:
        if inst_type == "Index Options":
            underlying = st.selectbox("Select Index", list(INDICES.keys()))
            lot_size   = INDICES[underlying]["lot"]
            st.caption(f"Lot size: **{lot_size}**")
            spot_sym, spot_exch = INDEX_SPOT_MAP[underlying]
            spot_price, spot_src = get_live_price(spot_sym, spot_exch)
        else:
            underlying = st.selectbox("Select Stock", FO_STOCKS)
            lot_size   = FO_STOCKS_LOT.get(underlying, 500)
            st.caption(f"Lot size: **{lot_size}**")
            spot_price, spot_src = get_live_price(underlying, "NSE")

        displayed_spot = render_price_badge(spot_price, spot_src, label="Spot Price")

        if displayed_spot is None:
            if spot_src == "auth_error":
                st.stop()  # No point continuing without auth
            # WHY: Use a safe fallback so strike slider doesn't crash
            spot_price = 24000.0 if inst_type == "Index Options" else 1000.0
            st.info(f"ℹ️ Using ₹{spot_price:,.0f} as placeholder for strike range only.")
        else:
            spot_price = displayed_spot

    with col2:
        expiry_type = st.radio("Expiry Type", ["Weekly", "Monthly"], horizontal=True)
        expiries    = get_weekly_expiries(5) if expiry_type == "Weekly" else get_monthly_expiries(3)
        expiry      = st.selectbox("Select Expiry", expiries)
        opt_type    = st.radio("Option Type", ["CE", "PE"], horizontal=True)

        # WHY: Theta (time decay) is fastest in last 1-2 days before expiry
        dte = days_to_expiry(expiry)
        if dte == 0:
            st.error("🚨 Expiry is **TODAY** — extreme time decay, trade carefully!")
        elif dte <= 2:
            st.warning(f"⚠️ Only **{dte} day(s)** to expiry — high time decay risk!")

    # ── Strike price slider ────────────────────────────────────────────────
    step    = 50 if underlying in ["NIFTY", "FINNIFTY", "MIDCPNIFTY"] else 100 if underlying == "BANKNIFTY" else 50
    strikes = get_strike_range(spot_price, step=step, count=30)
    atm     = round(spot_price / step) * step
    # WHY: Clamp ATM to nearest strike in list if spot moved since list was built
    if atm not in strikes:
        atm = min(strikes, key=lambda x: abs(x - spot_price))

    strike = st.select_slider("Strike Price", options=strikes, value=atm)

    diff = strike - atm
    if diff == 0:
        st.caption("🎯 **ATM** — At The Money")
    elif (opt_type == "CE" and diff < 0) or (opt_type == "PE" and diff > 0):
        st.caption(f"💚 **ITM** — In The Money by **{abs(diff)}** points")
    else:
        st.caption(f"🔴 **OTM** — Out of The Money by **{abs(diff)}** points")

    # ── Option price ───────────────────────────────────────────────────────
    opt_price_raw, opt_src = get_option_price(underlying, expiry, strike, opt_type)
    option_price = render_price_badge(opt_price_raw, opt_src, label="Option Premium")

    if option_price is None:
        if opt_src == "auth_error":
            st.stop()
        # WHY: Let user manually enter premium when live fetch fails
        option_price = st.number_input(
            "Enter Option Premium manually (₹)",
            min_value=0.05, value=100.0, step=0.05,
            help="Check NSE website or Kite app for current premium"
        )

    # ── Order summary before placing ───────────────────────────────────────
    col3, col4 = st.columns(2)
    with col3:
        lots = st.number_input("Number of Lots", min_value=1, value=1, step=1)
    with col4:
        total_qty  = lots * lot_size
        total_cost = option_price * total_qty
        st.info(f"**Qty:** {total_qty}  |  **Total:** ₹ {total_cost:,.2f}")

    action = st.radio("Action", ["BUY", "SELL"], horizontal=True)

    # WHY: Show remaining capital BEFORE clicking — helps avoid failed order
    _pf = load_fo_portfolio()
    if action == "BUY":
        remaining = _pf["cash"] - total_cost
        if remaining < 0:
            st.error(f"❌ Insufficient capital — short by ₹{abs(remaining):,.2f}")
        else:
            st.caption(f"Capital after this trade: ₹ {remaining:,.2f}")

    btn_label = (
        f"{'🟢 BUY' if action == 'BUY' else '🔴 SELL'} "
        f"{underlying} {strike} {opt_type}  |  {expiry}"
    )
    if st.button(btn_label, type="primary", width="stretch"):
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
                f"✅ **{t['action']}** {t['lots']} lot(s) × {t['lot_size']} = "
                f"{t['qty']} qty  |  {t['underlying']} {t['strike']} {t['opt_type']}  "
                f"|  @ ₹{t['price']:,.2f}  |  **Total: ₹{t['total']:,.2f}**"
            )
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# TAB 2 — OPEN POSITIONS
# ══════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("💼 Open Positions")
    portfolio = load_fo_portfolio()
    positions = portfolio.get("positions", {})

    if not positions:
        st.info("No open positions. Place your first F&O order! 👆")
    else:
        rows           = []
        total_invested = 0.0
        total_current  = 0.0
        has_stale      = False

        for key, pos in positions.items():
            cur_price, cur_src = get_option_price(
                pos["underlying"], pos["expiry"], pos["strike"], pos["opt_type"]
            )

            # WHY: If live price unavailable, fall back to avg buy price
            # This means P&L shows ₹0 for that row — correct and honest
            if cur_price is None:
                cur_price   = pos["avg_price"]
                price_label = f"₹ {cur_price:,.2f} ⚠️"
                has_stale   = True
            else:
                price_label = f"₹ {cur_price:,.2f} 📡"

            qty      = pos["lots"] * pos["lot_size"]
            invested = pos["avg_price"] * qty
            current  = cur_price * qty
            pnl      = current - invested
            pnl_pct  = (pnl / invested * 100) if invested else 0.0

            total_invested += invested
            total_current  += current

            # WHY: Show DTE per row — positions expiring soon need attention
            dte_pos = days_to_expiry(pos["expiry"])
            if dte_pos == 0:
                dte_label = "TODAY ⚠️"
            elif dte_pos < 0:
                dte_label = f"EXPIRED ({abs(dte_pos)}d ago)"
            else:
                dte_label = f"{dte_pos}d left"

            rows.append({
                "Underlying":    pos["underlying"],
                "Expiry":        f"{pos['expiry']} ({dte_label})",
                "Strike":        pos["strike"],
                "Type":          pos["opt_type"],
                "Lots":          pos["lots"],
                "Qty":           qty,
                "Avg Price":     f"₹ {pos['avg_price']:,.2f}",
                "Current Price": price_label,
                "Invested":      f"₹ {invested:,.2f}",
                "Current Value": f"₹ {current:,.2f}",
                "P&L":           f"₹ {pnl:,.2f}",
                "P&L %":         f"{pnl_pct:+.2f}%",
            })

        if has_stale:
            st.warning(
                "⚠️ Rows marked with ⚠️ could not fetch live price — "
                "showing avg buy price. P&L for those rows is ₹ 0 (not actual gain/loss)."
            )

        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        total_pnl     = total_current - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0.0
        net_worth     = portfolio["cash"] + total_current

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cash Balance",   f"₹ {portfolio['cash']:,.2f}")
        c2.metric("Premium Paid",   f"₹ {total_invested:,.2f}")
        c3.metric("Current Value",  f"₹ {total_current:,.2f}")
        c4.metric("Unrealized P&L", f"₹ {total_pnl:,.2f}", delta=f"{total_pnl_pct:+.2f}%")

        st.metric(
            "💰 Net Worth",
            f"₹ {net_worth:,.2f}",
            delta=f"₹ {net_worth - STARTING_CAPITAL:,.2f} from starting ₹{STARTING_CAPITAL:,.0f}",
        )


# ══════════════════════════════════════════════════════════════════════════
# TAB 3 — TRADE HISTORY
# ══════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("📋 Trade History")
    trades = load_fo_trades()

    if not trades:
        st.info("No trades yet. Start trading! 🚀")
    else:
        tdf = pd.DataFrame(list(reversed(trades)))  # newest first
        tdf = tdf[[
            "id", "timestamp", "underlying", "expiry",
            "strike", "opt_type", "action", "lots", "price", "total"
        ]]
        tdf.columns = ["#", "Time", "Underlying", "Expiry", "Strike", "Type", "Action", "Lots", "Price", "Total"]
        tdf["Price"] = tdf["Price"].apply(lambda x: f"₹ {x:,.2f}")
        tdf["Total"] = tdf["Total"].apply(lambda x: f"₹ {x:,.2f}")

        st.dataframe(tdf, width="stretch", hide_index=True, height=400)
        st.caption(f"Total trades recorded: **{len(trades)}**")

        # WHY: Confirm before clearing — deleted history can't be recovered
        if st.button("🗑️ Clear Trade History"):
            st.session_state["confirm_clear_hist"] = True

        if st.session_state.get("confirm_clear_hist"):
            st.warning("⚠️ This permanently deletes all trade history!")
            cy2, cn2 = st.columns(2)
            with cy2:
                if st.button("✅ Yes, Clear", width="stretch", key="clear_yes"):
                    save_fo_trades([])
                    st.session_state.pop("confirm_clear_hist", None)
                    st.success("Trade history cleared.")
                    st.rerun()
            with cn2:
                if st.button("❌ Cancel", width="stretch", key="clear_no"):
                    st.session_state.pop("confirm_clear_hist", None)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# TAB 4 — P&L SUMMARY
# ══════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("📊 P&L Summary")
    trades = load_fo_trades()

    if not trades:
        st.info("No trades to summarize yet!")
    else:
        df = pd.DataFrame(trades)

        # ── By Underlying ──────────────────────────────────────────────────
        # WHY: See which symbols you trade most and how much premium you deploy
        st.markdown("#### By Underlying")
        summary = df.groupby(["underlying", "opt_type"]).agg(
            Total_Trades  = ("id",     "count"),
            Buy_Trades    = ("action", lambda x: (x == "BUY").sum()),
            Sell_Trades   = ("action", lambda x: (x == "SELL").sum()),
            Total_Lots    = ("lots",   "sum"),
            Total_Premium = ("total",  "sum"),
        ).reset_index()
        summary["Total_Premium"] = summary["Total_Premium"].apply(lambda x: f"₹ {x:,.2f}")
        st.dataframe(summary, width="stretch", hide_index=True)

        # ── By Date ────────────────────────────────────────────────────────
        # WHY: Track your trading activity per day — helps spot overtrading
        st.markdown("#### By Date")
        df["date"] = pd.to_datetime(df["timestamp"]).dt.date
        daily = (
            df.groupby("date")
            .agg(Trades=("id", "count"), Total_Premium=("total", "sum"))
            .reset_index()
            .sort_values("date", ascending=False)
        )
        daily["Total_Premium"] = daily["Total_Premium"].apply(lambda x: f"₹ {x:,.2f}")
        st.dataframe(daily, width="stretch", hide_index=True)

        # ── Capital summary ────────────────────────────────────────────────
        # WHY: Realized P&L = what you received selling minus what you paid buying.
        # This is your actual booked profit/loss, ignoring open positions.
        st.markdown("#### Capital Summary")
        total_bought = df[df["action"] == "BUY"]["total"].sum()
        total_sold   = df[df["action"] == "SELL"]["total"].sum()
        realized_pnl = total_sold - total_bought

        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Total Premium Bought", f"₹ {total_bought:,.2f}")
        sc2.metric("Total Premium Sold",   f"₹ {total_sold:,.2f}")
        sc3.metric(
            "Realized P&L",
            f"₹ {realized_pnl:,.2f}",
            delta="Profit ✅" if realized_pnl >= 0 else "Loss ❌",
        )
