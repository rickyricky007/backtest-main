"""Trading Assistant Chatbot — AI-powered chat with live Kite data."""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import anthropic
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import auth_streamlit as auth
import kite_data as kd
from market_intelligence import market_session_status, expiry_alert
from db import read_df

load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")

client = None
if API_KEY:
    try:
        client = anthropic.Anthropic(api_key=API_KEY)
    except Exception as e:
        st.error(f"❌ Failed to initialize Anthropic client: {e}")

st.set_page_config(page_title="Trading Assistant", page_icon="🤖", layout="wide")
st.title("🤖 Trading Assistant")
st.caption("Ask me anything about your trading data!")

auth.render_auth_cleared_banner()


# ── Global market helpers ─────────────────────────────────────────────────────

def _gift_nifty_symbol() -> str:
    """Return active GIFT Nifty futures symbol — switches to next month after expiry."""
    import calendar
    month_map = {
        1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",
        7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"
    }
    now   = datetime.now()
    year  = now.year
    month = now.month
    # Last Thursday of current month
    last_thu = max(
        w[3] for w in calendar.monthcalendar(year, month) if w[3] != 0
    )
    # After expiry — use next month
    if now.day > last_thu:
        month += 1
        if month > 12:
            month = 1
            year += 1
    return f"NSE_IFSC:NIFTY{str(year)[2:]}{month_map[month]}FUT"


def get_global_market_data() -> dict:
    """Fetch US futures, SGX Nifty proxy, Gold, Crude via yfinance."""
    result = {}
    try:
        import yfinance as yf
        targets = {
            "S&P 500 Futures":    "ES=F",
            "Nasdaq Futures":     "NQ=F",
            "Dow Futures":        "YM=F",
            "Crude Oil (WTI)":    "CL=F",
            "Gold":               "GC=F",
            "SGX Nifty (proxy)":  "^NSEI",
        }
        for name, sym in targets.items():
            try:
                hist  = yf.Ticker(sym).history(period="1d", interval="1m")
                price = float(hist["Close"].iloc[-1]) if not hist.empty else None
                result[name] = {"symbol": sym, "price": price}
            except Exception:
                result[name] = {"symbol": sym, "price": None}
    except ImportError:
        result["error"] = "yfinance not installed — run: pip install yfinance"
    return result


# ── Kite client — auto-built from saved token, no manual login needed ────────
def get_kite_client():
    """
    Build a live KiteConnect client using the token saved by terminal login.
    Never asks the user to log in again — just reads .kite_access_token.
    Falls back gracefully if token is missing or expired.
    """
    try:
        # Step 1: try kite_data's own builder (works if it exists)
        try:
            k = kd.kite()
            if k:
                return k
        except AttributeError:
            pass  # kd.kite() doesn't exist — build it ourselves below

        # Step 2: build directly from saved token + API key from .env
        from kiteconnect import KiteConnect

        api_key = os.getenv("API_KEY")
        if not api_key:
            st.sidebar.error("❌ API_KEY missing from .env")
            return None

        token = kd.load_access_token()
        if not token:
            st.sidebar.warning("⚠️ No Kite token found. Run terminal login first.")
            return None

        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(token)
        return kite

    except Exception as e:
        st.sidebar.error(f"❌ Kite client error: {e}")
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────
def fmt_money(v) -> str:
    try:
        if v is None or v == "N/A":
            return "N/A"
        return f"₹{float(v):,.2f}"
    except Exception:
        return f"₹{v}"


def get_live_snapshot() -> dict:
    snapshot = {
        "connected":     False,
        "error":         None,
        "indices":       {},
        "gift_nifty":    {},
        "global_market": get_global_market_data(),
        "funds":         {},
        "holdings":      [],
        "positions":     {"day": [], "net": [], "open": []},
    }

    kite = get_kite_client()
    if not kite:
        snapshot["error"] = "Kite not connected"
        return snapshot

    snapshot["connected"] = True

    # Indices
    try:
        symbols = [
            "NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX",
            "NSE:NIFTY FIN SERVICE", "NSE:NIFTY MID SELECT",
        ]
        ltp = kite.ltp(symbols)
        snapshot["indices"] = {
            "NIFTY 50":     ltp.get("NSE:NIFTY 50", {}).get("last_price"),
            "BANK NIFTY":   ltp.get("NSE:NIFTY BANK", {}).get("last_price"),
            "SENSEX":       ltp.get("BSE:SENSEX", {}).get("last_price"),
            "FIN NIFTY":    ltp.get("NSE:NIFTY FIN SERVICE", {}).get("last_price"),
            "MIDCAP NIFTY": ltp.get("NSE:NIFTY MID SELECT", {}).get("last_price"),
        }
    except Exception as e:
        snapshot["indices_error"] = str(e)
        st.sidebar.warning(f"⚠️ Indices: {e}")

    # GIFT Nifty — dynamic expiry (switches to next month after last Thursday)
    try:
        gift_symbol = _gift_nifty_symbol()
        gift_ltp    = kite.ltp([gift_symbol])
        snapshot["gift_nifty"] = {
            "symbol": gift_symbol,
            "price":  gift_ltp.get(gift_symbol, {}).get("last_price"),
        }
    except Exception as e:
        snapshot["gift_nifty_error"] = str(e)
        st.sidebar.warning(f"⚠️ GIFT Nifty: {e}")

    # Funds
    try:
        funds = kite.margins()
        eq    = funds.get("equity", {})
        avail = eq.get("available", {})
        used  = eq.get("utilised", {})
        snapshot["funds"] = {
            "available_cash":  avail.get("cash"),
            "live_balance":    avail.get("live_balance"),
            "opening_balance": avail.get("opening_balance"),
            "collateral":      avail.get("collateral"),
            "net_equity":      eq.get("net"),
            "used_margin":     used.get("debits"),
            "span":            used.get("span"),
            "exposure":        used.get("exposure"),
            "m2m_realised":    used.get("m2m_realised"),
            "commodity_net":   funds.get("commodity", {}).get("net"),
        }
    except Exception as e:
        snapshot["funds_error"] = str(e)
        st.sidebar.warning(f"⚠️ Funds: {e}")

    # Holdings
    try:
        holdings = kite.holdings() or []
        enriched = []
        for h in holdings:
            qty      = h.get("quantity", 0) or 0
            avg      = h.get("average_price", 0) or 0
            ltp_     = h.get("last_price", 0) or 0
            invested = avg * qty
            current  = ltp_ * qty
            pnl      = current - invested
            enriched.append({
                "tradingsymbol": h.get("tradingsymbol"),
                "exchange":      h.get("exchange"),
                "quantity":      qty,
                "average_price": avg,
                "last_price":    ltp_,
                "invested":      invested,
                "current_value": current,
                "pnl":           pnl,
                "pnl_pct":       (pnl / invested * 100) if invested else 0,
            })
        snapshot["holdings"] = enriched
    except Exception as e:
        snapshot["holdings_error"] = str(e)
        st.sidebar.warning(f"⚠️ Holdings: {e}")

    # Positions
    try:
        positions = kite.positions() or {}
        day_pos   = positions.get("day", []) or []
        net_pos   = positions.get("net", []) or []
        open_pos  = [p for p in net_pos if (p.get("quantity", 0) or 0) != 0]
        snapshot["positions"] = {"day": day_pos, "net": net_pos, "open": open_pos}
    except Exception as e:
        snapshot["positions_error"] = str(e)
        st.sidebar.warning(f"⚠️ Positions: {e}")

    return snapshot


def build_market_context(snapshot: dict) -> str:
    if not snapshot.get("connected"):
        return "⚠️ Kite not connected. No live account data available.\n"

    ctx = ""

    indices = snapshot.get("indices", {})
    if indices:
        ctx += "\n📡 Live Index Prices:\n"
        for name, val in indices.items():
            ctx += f"- {name}: {fmt_money(val)}\n"

    gift = snapshot.get("gift_nifty", {})
    if gift.get("price") is not None:
        ctx += f"- GIFT Nifty: {fmt_money(gift['price'])} ({gift.get('symbol')})\n"

    global_mkt = snapshot.get("global_market", {})
    if global_mkt and "error" not in global_mkt:
        ctx += "\n🌍 Global Markets (via yfinance):\n"
        for name, d in global_mkt.items():
            price = d.get("price")
            if price:
                ctx += f"- {name}: {price:,.2f}\n"

    funds = snapshot.get("funds", {})
    if funds:
        ctx += "\n💰 Account Funds:\n"
        ctx += f"- Available Cash: {fmt_money(funds.get('available_cash'))}\n"
        ctx += f"- Live Balance:   {fmt_money(funds.get('live_balance'))}\n"
        ctx += f"- Net Equity:     {fmt_money(funds.get('net_equity'))}\n"
        ctx += f"- Used Margin:    {fmt_money(funds.get('used_margin'))}\n"

    holdings = snapshot.get("holdings", [])
    if holdings:
        ti = sum(h["invested"] for h in holdings)
        tc = sum(h["current_value"] for h in holdings)
        tp = tc - ti
        ctx += f"\n📦 Holdings ({len(holdings)} stocks):\n"
        ctx += f"- Invested: {fmt_money(ti)} | Current: {fmt_money(tc)} | P&L: {fmt_money(tp)}\n"
        for h in sorted(holdings, key=lambda x: x["current_value"], reverse=True)[:5]:
            ctx += (f"  {h['tradingsymbol']}: {h['quantity']} qty @ {fmt_money(h['average_price'])}"
                    f" | LTP {fmt_money(h['last_price'])} | P&L {fmt_money(h['pnl'])}\n")

    open_pos = snapshot.get("positions", {}).get("open", [])
    ctx += f"\n📊 Open Positions: {len(open_pos)}\n"
    for p in open_pos[:5]:
        ctx += f"  {p.get('tradingsymbol')}: qty={p.get('quantity')} | P&L {fmt_money(p.get('pnl', 0))}\n"

    return ctx


def get_db_context() -> str:
    ctx = ""
    try:
        # Today's strategy trades
        today = datetime.now().strftime("%Y-%m-%d")
        trades = read_df(
            "SELECT strategy, symbol, action, price, pnl, timestamp "
            "FROM strategy_trades WHERE DATE(timestamp) = ? ORDER BY timestamp DESC LIMIT 10",
            (today,)
        )
        if not trades.empty:
            total_pnl = trades["pnl"].sum()
            ctx += f"\n📊 Today's Strategy Trades ({len(trades)}):\n"
            ctx += f"- Total P&L today: ₹{total_pnl:+,.0f}\n"
            for _, r in trades.head(5).iterrows():
                ctx += f"  {r['strategy']} | {r['symbol']} {r['action']} @ ₹{r['price']} | P&L ₹{r['pnl']:+.0f}\n"

        # Recent orders
        orders = read_df(
            "SELECT symbol, action, quantity, fill_price, mode, status, timestamp "
            "FROM engine_orders ORDER BY timestamp DESC LIMIT 5"
        )
        if not orders.empty:
            ctx += f"\n📋 Recent Orders ({len(orders)}):\n"
            for _, r in orders.iterrows():
                ctx += f"  [{r['mode']}] {r['action']} {r['quantity']} {r['symbol']} @ ₹{r['fill_price']} — {r['status']}\n"

        # Journal entries
        journal = read_df(
            "SELECT date, symbol, direction, pnl, setup, notes "
            "FROM trade_journal ORDER BY date DESC LIMIT 3"
        )
        if not journal.empty:
            ctx += f"\n📓 Trade Journal (last {len(journal)} entries):\n"
            for _, r in journal.iterrows():
                ctx += f"  {r['date']} | {r['symbol']} {r['direction']} | P&L ₹{r['pnl']:+.0f} | {r['setup']}\n"

    except Exception:
        pass
    return ctx


def get_market_intelligence_context() -> str:
    """Add global market hours + expiry info to chatbot context."""
    ctx = ""
    try:
        session = market_session_status()
        ctx += f"\n🌍 Market Sessions ({session['ist_time']}):\n"
        ctx += f"- NSE Phase: {session['nse_phase']}\n"
        for s in session["sessions"]:
            ctx += f"- {s['market']}: {s['status']}\n"

        expiry = expiry_alert()
        ctx += f"\n📅 Expiry Info:\n"
        ctx += f"- Weekly expiry: {expiry['weekly_expiry']} (in {expiry['dte_weekly']} days)\n"
        ctx += f"- Monthly expiry: {expiry['monthly_expiry']} (in {expiry['dte_monthly']} days)\n"
        if expiry["alerts"]:
            ctx += "- Alerts:\n"
            for a in expiry["alerts"]:
                ctx += f"  {a}\n"

    except Exception:
        pass
    return ctx


def read_uploaded_file(uploaded_file) -> str:
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
            return f"\n📄 CSV ({uploaded_file.name}):\n{df.head(10).to_string()}\n"
        if uploaded_file.name.endswith(".json"):
            content = json.load(uploaded_file)
            return f"\n📄 JSON ({uploaded_file.name}):\n{json.dumps(content, indent=2)[:1500]}\n"
        if uploaded_file.name.endswith(".py"):
            content = uploaded_file.read().decode("utf-8")[:1500]
            return f"\n📄 Python ({uploaded_file.name}):\n```python\n{content}\n```\n"
        content = uploaded_file.read().decode("utf-8", errors="ignore")[:1000]
        return f"\n📄 File ({uploaded_file.name}):\n{content}\n"
    except Exception as e:
        return f"\n⚠️ Could not read {uploaded_file.name}: {e}\n"


def build_system_context(auto_read: bool, uploaded_files, snapshot: dict) -> str:
    ctx = """You are an expert AI trading assistant built into Ricky's algo trading platform.
You have COMPLETE knowledge of every part of this system. Never say you don't have access to
configuration details — all facts are listed below.

════════════════════════════════════════════════════════
SYSTEM IDENTITY
════════════════════════════════════════════════════════
Owner       : Ricky
Broker      : Zerodha (KiteConnect API)
Exchange    : NSE / BSE / NFO (F&O)
Platform    : Streamlit dashboard (localhost:8501)
Language    : Python 3
Database    : dashboard.sqlite  (SQLite, WAL mode)
DB Tables   : engine_orders | strategy_trades | sl_positions | trade_journal
Config file : config.py  (imports from .env)
Logger      : logger.py  → get_logger("module_name")
Start cmd   : streamlit run app.py
Auth cmd    : python generate_token.py <request_token>   ← run ONCE every morning

════════════════════════════════════════════════════════
ENVIRONMENT VARIABLES (.env)
════════════════════════════════════════════════════════
API_KEY / KITE_API_KEY          → Zerodha API key
API_SECRET / KITE_API_SECRET    → Zerodha API secret
TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN → Telegram bot
TELEGRAM_CHAT_ID                → Telegram chat ID
ANTHROPIC_API_KEY               → Claude AI key (this chatbot)

════════════════════════════════════════════════════════
ALL 18 DASHBOARD PAGES
════════════════════════════════════════════════════════
1.  Holdings          → Full holdings table, invested vs current, P&L export
2.  Positions         → Net vs intraday positions, live P&L
3.  Funds             → Available cash, margins, collateral breakdown
4.  Historical Data   → Fetch OHLCV from Kite, display chart + table
5.  Strategy Hub      → Run/stop all strategies, PAPER/LIVE toggle per strategy
6.  Chatbot           → This AI assistant (YOU)
7.  ST Paper Trading  → Stock paper trading simulator
8.  FO Paper Trading  → F&O paper trading with real Kite prices
9.  RSI Strategy      → Multi-timeframe RSI scanner (5m + 15m confluence)
10. SMA Strategy      → SMA crossover signals
11. Options Chain     → ALL F&O indices + 180 stocks, IV, Greeks, PCR, OI chart, straddle launcher
12. FO Dashboard      → IV rank, expiry calendar, portfolio Greeks
13. Strategy PnL      → Historical P&L per strategy with charts
14. Trade Journal     → Manual trade diary with setup tags and analytics
15. System Status     → Service health, logs, DB stats, process monitor
16. Backtest          → Walk-forward backtesting, parameter optimisation
17. Signal Scanner    → Live multi-symbol confluence scanner, BUY/SELL/WAIT
18. Charts            → Plotly interactive charts, any F&O symbol, multi-timeframe

════════════════════════════════════════════════════════
SIGNAL SCORING SYSTEM (indicators.py)
════════════════════════════════════════════════════════
10 indicators — each returns +weight, -weight, or 0:
  RSI (weight 2)          → <30 BUY, >70 SELL
  MACD (weight 2)         → crossover direction
  Bollinger Bands (wt 2)  → price vs bands
  Supertrend (weight 2)   → trend direction
  EMA Crossover (wt 2)    → 9 EMA vs 21 EMA
  VWAP (weight 1)         → price above/below VWAP
  Volume Spike (weight 1) → >1.5x average volume
  ADX (weight 1)          → trend strength >25
  Stochastic (weight 1)   → <20 BUY, >80 SELL
  OI Change (weight 1)    → open interest direction

Score range : -15 to +15
BUY signal  : score ≥ +6
SELL signal : score ≤ -6
WAIT        : between -6 and +6

════════════════════════════════════════════════════════
F&O UNIVERSE (fo_symbols.py)
════════════════════════════════════════════════════════
Indices (6) : NIFTY 50, BANK NIFTY, FINNIFTY, MIDCAP NIFTY, SENSEX, BANKEX
Stocks      : ~180 NSE F&O stocks across sectors
Top 50 liquid stocks used for fast scans
All symbols imported from fo_symbols.py — single source of truth

════════════════════════════════════════════════════════
EXECUTION LAYER
════════════════════════════════════════════════════════
PAPER mode  → logs to engine_orders table, no real order sent
LIVE mode   → real KiteConnect API order, also logged to DB
Toggle      → one switch at OrderManager level — no code change needed
Order types → market, limit, SL, SL-M, bracket, cover
Risk checks → daily loss limit, max positions, Greeks exposure
Stop Loss   → trailing SL and target exits via stop_loss_manager.py

════════════════════════════════════════════════════════
KEY FILES
════════════════════════════════════════════════════════
app.py              → main Streamlit entry point
kite_data.py        → Kite API helpers, token loading
config.py           → centralised env var loader
generate_token.py   → morning auth — run once per day
ticker_service.py   → WebSocket live prices → ticker_data.json
signal_engine.py    → multi-symbol confluence scanner
indicators.py       → 10-indicator scoring functions
fo_symbols.py       → complete F&O symbol registry
market_intelligence.py → OI analysis, expiry alerts, manipulation detection
order_manager.py    → paper + live order routing
risk_manager.py     → daily loss / position limits
stop_loss_manager.py → trailing SL / targets
db.py               → SQLite helpers (execute, query, read_df)
logger.py           → central rotating logger
update_docs.py      → auto-regenerates CLAUDE.md

════════════════════════════════════════════════════════
MARKET INTELLIGENCE
════════════════════════════════════════════════════════
OI signals  → Long Buildup | Short Buildup | Short Covering | Long Unwinding
Max Pain    → strike where total option buyer loss is maximum (price gravitates here on expiry)
PCR         → Put-Call Ratio: >1.5 extreme fear | <0.5 extreme greed
Manipulation signals → volume spike >3x, OI spike no price move, expiry day traps
Expiry      → NSE weekly (every Thursday) | monthly (last Thursday of month)

════════════════════════════════════════════════════════
GLOBAL MARKET SESSIONS (all times IST)
════════════════════════════════════════════════════════
NSE/BSE     → 09:15 – 15:30 IST
SGX Nifty   → 06:30 – 23:00 IST
London LSE  → 13:30 – 22:00 IST
NYSE/NASDAQ → 19:00 – 01:30 IST (approx)
Tokyo TSE   → 05:30 – 11:30 IST

════════════════════════════════════════════════════════
RULES FOR YOUR RESPONSES
════════════════════════════════════════════════════════
- Always use ₹ for Indian Rupees
- Be concise, specific and actionable
- NEVER say "I don't have access to config" — all config facts are above
- If Kite not connected → tell user to run: python generate_token.py <request_token>
- For trade advice → always mention risk management and position sizing
- For DB questions → database name is dashboard.sqlite, 4 tables listed above
- For page questions → refer to the 18 pages listed above by name

"""
    ctx += build_market_context(snapshot)
    ctx += get_db_context()
    ctx += get_market_intelligence_context()

    if auto_read:
        for fp in sorted(glob.glob("*.py") + glob.glob("pages/*.py")):
            try:
                ctx += f"\n📄 {fp}:\n```python\n{open(fp).read()[:600]}\n```\n"
            except Exception:
                pass

    if uploaded_files:
        for f in uploaded_files:
            f.seek(0)
            ctx += read_uploaded_file(f)

    return ctx[:16000]


# ── Direct replies (no Claude token used) ────────────────────────────────────
def get_direct_live_reply(prompt: str, snapshot: dict) -> str | None:
    q = prompt.lower().strip()
    live_keywords = [
        "balance", "fund", "funds", "cash", "margin", "holding", "holdings",
        "position", "positions", "nifty", "bank nifty", "sensex", "gift nifty",
        "fin nifty", "midcap", "index", "indices", "portfolio",
    ]

    # ── Project knowledge — instant answers, no Claude token needed ──────────
    if any(k in q for k in ["database", "db name", "database name", "sqlite", "what db", "which db"]):
        return (
            "🗄️ **Database:** `dashboard.sqlite` (SQLite, WAL mode)\n\n"
            "**4 tables:**\n"
            "- `engine_orders` — all paper + live orders with fill info\n"
            "- `strategy_trades` — strategy signal log with P&L\n"
            "- `sl_positions` — active stop-loss positions\n"
            "- `trade_journal` — manual trade diary entries\n\n"
            "Located in `ricky_1/dashboard.sqlite`"
        )

    if any(k in q for k in ["how many page", "all page", "list page", "what page", "dashboard page"]):
        return (
            "📋 **18 Dashboard Pages:**\n\n"
            "1. Holdings  2. Positions  3. Funds  4. Historical Data\n"
            "5. Strategy Hub  6. Chatbot (you're here)  7. ST Paper Trading\n"
            "8. FO Paper Trading  9. RSI Strategy  10. SMA Strategy\n"
            "11. Options Chain  12. FO Dashboard  13. Strategy PnL\n"
            "14. Trade Journal  15. System Status  16. Backtest\n"
            "17. Signal Scanner  18. Charts"
        )

    if "scoring" in q or ("score" in q and "indicator" in q) or "confluence" in q or "buy threshold" in q or "sell threshold" in q:
        return (
            "📊 **Signal Scoring System (10 indicators):**\n\n"
            "RSI (±2) | MACD (±2) | Bollinger Bands (±2) | Supertrend (±2) | EMA Cross (±2)\n"
            "VWAP (±1) | Volume Spike (±1) | ADX (±1) | Stochastic (±1) | OI Change (±1)\n\n"
            "**Score range:** -15 to +15\n"
            "🟢 **BUY** ≥ +6  |  🔴 **SELL** ≤ -6  |  ⚪ **WAIT** between -6 and +6"
        )

    if any(k in q for k in ["how to start", "start the app", "run the app", "how to run", "startup"]):
        return (
            "🚀 **How to start:**\n\n"
            "```bash\n"
            "cd ~/algo_trading/ricky_1\n"
            "source venv/bin/activate\n"
            "python generate_token.py <request_token>   # once per morning\n"
            "python ticker_service.py                   # live WebSocket prices\n"
            "streamlit run app.py                       # dashboard\n"
            "```\n"
            "Or: `python process_guard.py` starts everything at once."
        )

    if any(k in q for k in ["paper mode", "live mode", "switch mode", "paper vs live", "paper trade vs"]):
        return (
            "📄 **PAPER vs LIVE:**\n\n"
            "- **PAPER** → logs to `engine_orders` table, no real money\n"
            "- **LIVE** → real KiteConnect API order + logged to DB\n\n"
            "One toggle switch in Signal Scanner or Strategy Hub. No code changes needed."
        )

    if any(k in q for k in ["f&o universe", "how many stocks", "all symbols", "fo stocks", "symbol universe"]):
        return (
            "📈 **F&O Universe:**\n\n"
            "**Indices (6):** NIFTY 50, BANK NIFTY, FINNIFTY, MIDCAP NIFTY, SENSEX, BANKEX\n"
            "**Stocks:** ~180 NSE F&O stocks\n"
            "**Top 50 Liquid** used for fast scans\n\n"
            "All from `fo_symbols.py` — single source of truth."
        )

    if any(k in q for k in ["expiry", "weekly expiry", "monthly expiry", "days to expiry", "dte"]):
        try:
            from market_intelligence import expiry_alert
            exp = expiry_alert()
            msg = (
                f"📅 **Expiry Info:**\n\n"
                f"- Weekly:  **{exp['weekly_expiry']}** ({exp['dte_weekly']} days)\n"
                f"- Monthly: **{exp['monthly_expiry']}** ({exp['dte_monthly']} days)\n"
            )
            if exp["alerts"]:
                msg += "\n**Alerts:**\n" + "\n".join(exp["alerts"])
            return msg
        except Exception:
            pass

    if any(k in q for k in ["market open", "is market open", "market status", "market time", "session status", "nse open"]):
        try:
            from market_intelligence import market_session_status
            sess = market_session_status()
            icon = "🟢" if sess["nse_open"] else "🔴"
            lines = [f"🌍 **Market Sessions** — {sess['ist_time']}\n",
                     f"{icon} NSE: **{sess['nse_phase']}**\n"]
            for s in sess["sessions"]:
                lines.append(f"- {s['market']}: {s['status']}")
            return "\n".join(lines)
        except Exception:
            pass

    if not snapshot.get("connected"):
        if any(k in q for k in live_keywords):
            return (
                "⚠️ Kite is not connected.\n\n"
                "**Fix:** Run terminal login once:\n"
                "```\nstreamlit run Home.py\n```\n"
                "Login via the browser popup — the token is saved automatically "
                "and the chatbot will connect without any extra steps."
            )
        return None

    funds     = snapshot.get("funds", {})
    holdings  = snapshot.get("holdings", [])
    positions = snapshot.get("positions", {})
    indices   = snapshot.get("indices", {})
    gift      = snapshot.get("gift_nifty", {})

    if any(k in q for k in ["balance", "fund", "cash", "margin", "net equity"]):
        return (
            f"💰 **Fund Balance**\n\n"
            f"- Available Cash: {fmt_money(funds.get('available_cash'))}\n"
            f"- Live Balance:   {fmt_money(funds.get('live_balance'))}\n"
            f"- Net Equity:     {fmt_money(funds.get('net_equity'))}\n"
            f"- Used Margin:    {fmt_money(funds.get('used_margin'))}\n"
            f"- Commodity Net:  {fmt_money(funds.get('commodity_net'))}"
        )

    if any(k in q for k in ["holding", "holdings", "portfolio"]):
        if not holdings:
            return "📦 **Holdings**\n\nNo holdings found."
        ti = sum(h["invested"] for h in holdings)
        tc = sum(h["current_value"] for h in holdings)
        tp = tc - ti
        lines = [
            f"📦 **Holdings** ({len(holdings)} stocks)\n",
            f"- Invested: {fmt_money(ti)}",
            f"- Current:  {fmt_money(tc)}",
            f"- P&L:      {fmt_money(tp)} ({(tp / ti * 100) if ti else 0:.2f}%)\n",
            "**Top 5:**",
        ]
        for h in sorted(holdings, key=lambda x: x["current_value"], reverse=True)[:5]:
            lines.append(
                f"- {h['tradingsymbol']}: {h['quantity']} qty "
                f"| LTP {fmt_money(h['last_price'])} | P&L {fmt_money(h['pnl'])}"
            )
        return "\n".join(lines)

    if any(k in q for k in ["position", "positions", "open trade"]):
        open_pos = positions.get("open", [])
        day_pos  = positions.get("day", [])
        lines    = [
            f"📊 **Positions**\n",
            f"- Open: {len(open_pos)}  |  Today's trades: {len(day_pos)}",
        ]
        for p in open_pos[:5]:
            lines.append(
                f"  - {p.get('tradingsymbol')}: qty={p.get('quantity')} "
                f"| P&L {fmt_money(p.get('pnl', 0))}"
            )
        return "\n".join(lines)

    if "gift nifty" in q or ("gift" in q and "nifty" in q):
        price  = gift.get("price")
        symbol = gift.get("symbol", "N/A")
        return (
            f"📈 **GIFT Nifty**: {fmt_money(price)}\nSymbol: `{symbol}`"
            if price
            else f"📈 **GIFT Nifty**: Unavailable\nSymbol tried: `{symbol}`"
        )

    # ── Global market direct replies ──────────────────────────────────────────
    global_mkt = snapshot.get("global_market", {})

    def _gval(name: str) -> str:
        d = global_mkt.get(name, {})
        p = d.get("price")
        return f"{p:,.2f}" if p else "Unavailable"

    if any(k in q for k in ["us futures", "us market", "s&p", "sp500", "s&p 500", "/es", "es=f"]):
        return (
            f"🇺🇸 **US Futures**\n\n"
            f"- S&P 500 Futures : {_gval('S&P 500 Futures')}\n"
            f"- Nasdaq Futures  : {_gval('Nasdaq Futures')}\n"
            f"- Dow Futures     : {_gval('Dow Futures')}\n\n"
            f"_Source: yfinance (15-min delay)_"
        )

    if any(k in q for k in ["crude", "oil", "cl=f", "wti"]):
        return f"🛢️ **Crude Oil (WTI)**: {_gval('Crude Oil (WTI)')}\n_Source: yfinance_"

    if any(k in q for k in ["gold", "gc=f", "xau"]):
        return f"🥇 **Gold**: {_gval('Gold')}\n_Source: yfinance_"

    if any(k in q for k in ["sgx", "sgx nifty", "singapore nifty"]):
        return (
            f"📈 **SGX Nifty (proxy — Nifty 50 index)**: {_gval('SGX Nifty (proxy)')}\n\n"
            f"_Note: True SGX Nifty requires a Singapore broker feed. "
            f"This uses NSE Nifty 50 as a close proxy._"
        )

    if any(k in q for k in ["nasdaq", "nq=f", "/nq"]):
        return f"📊 **Nasdaq Futures**: {_gval('Nasdaq Futures')}\n_Source: yfinance_"

    if any(k in q for k in ["dow", "ym=f", "/ym"]):
        return f"📊 **Dow Futures**: {_gval('Dow Futures')}\n_Source: yfinance_"

    if any(k in q for k in ["global market", "world market", "international"]):
        lines = ["🌍 **Global Markets**\n"]
        for name, d in global_mkt.items():
            p = d.get("price")
            lines.append(f"- {name}: {p:,.2f}" if p else f"- {name}: Unavailable")
        lines.append("\n_Source: yfinance (15-min delay)_")
        return "\n".join(lines)

    if "bank nifty" in q:
        return f"📈 **Bank Nifty**: {fmt_money(indices.get('BANK NIFTY'))}"
    if "sensex" in q:
        return f"📈 **Sensex**: {fmt_money(indices.get('SENSEX'))}"
    if "fin nifty" in q or "finnifty" in q:
        return f"📈 **Fin Nifty**: {fmt_money(indices.get('FIN NIFTY'))}"
    if "midcap" in q:
        return f"📈 **Midcap Nifty**: {fmt_money(indices.get('MIDCAP NIFTY'))}"
    if "nifty" in q or "index" in q or "indices" in q or "market" in q:
        return (
            f"📡 **Live Indices**\n\n"
            f"- Nifty 50:     {fmt_money(indices.get('NIFTY 50'))}\n"
            f"- Bank Nifty:   {fmt_money(indices.get('BANK NIFTY'))}\n"
            f"- Sensex:       {fmt_money(indices.get('SENSEX'))}\n"
            f"- Fin Nifty:    {fmt_money(indices.get('FIN NIFTY'))}\n"
            f"- Midcap Nifty: {fmt_money(indices.get('MIDCAP NIFTY'))}"
        )

    return None


# ── Sidebar — clean, no manual Kite session needed ───────────────────────────
with st.sidebar:
    st.subheader("⚙️ Settings")
    auto_read = st.toggle(
        "📂 Read project files", value=False,
        help="Include .py source files in context (uses more tokens)"
    )
    uploaded_files = st.file_uploader(
        "📎 Upload Files", type=["csv", "py", "json", "txt"],
        accept_multiple_files=True
    )
    st.divider()
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()

    # ── Kite status — auto, no manual login expander ──────────────────────
    st.caption("📡 Kite Status")
    token = kd.load_access_token()
    if token:
        st.success("✅ Kite Connected (auto)")
        st.caption("Token loaded from terminal login.")
    else:
        st.error("❌ No token found")
        st.caption(
            "Run Streamlit from terminal and log in once via the browser popup. "
            "The chatbot will auto-connect after that — no manual steps needed here."
        )

    st.divider()
    auth.render_logout_controls(key="kite_logout_chatbot")


# ── Chat ──────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt := st.chat_input("Ask about balance, holdings, positions, indices..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    snapshot = get_live_snapshot()

    # 1) Direct reply — zero Claude tokens used
    direct = get_direct_live_reply(prompt, snapshot)
    if direct:
        with st.chat_message("assistant"):
            st.markdown(direct)
        st.session_state.messages.append({"role": "assistant", "content": direct})
        st.stop()

    # 2) Claude for everything else
    if not client:
        answer = (
            "⚠️ Add `ANTHROPIC_API_KEY` to your `.env` to enable AI chat. "
            "Live data queries (balance, holdings, indices) work without it."
        )
        with st.chat_message("assistant"):
            st.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.stop()

    system_ctx = build_system_context(auto_read, uploaded_files, snapshot)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1000,
                    system=system_ctx,
                    messages=st.session_state.messages[-12:],
                )
                answer = resp.content[0].text
            except anthropic.AuthenticationError:
                answer = "❌ Invalid Anthropic API key. Check your `.env` file."
            except anthropic.RateLimitError:
                answer = "⚠️ Rate limit hit. Wait a moment and try again."
            except anthropic.APIConnectionError:
                answer = "⚠️ Cannot reach Anthropic API. Check your internet."
            except Exception as e:
                answer = f"⚠️ Unexpected error: {e}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
