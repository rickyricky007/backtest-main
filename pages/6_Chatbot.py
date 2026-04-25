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
        "connected": False,
        "error": None,
        "indices": {},
        "gift_nifty": {},
        "funds": {},
        "holdings": [],
        "positions": {"day": [], "net": [], "open": []},
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

    # GIFT Nifty
    try:
        now = datetime.now()
        month_map = {
            1:"JAN", 2:"FEB", 3:"MAR", 4:"APR", 5:"MAY", 6:"JUN",
            7:"JUL", 8:"AUG", 9:"SEP", 10:"OCT", 11:"NOV", 12:"DEC"
        }
        gift_symbol = f"NSE_IFSC:NIFTY{now.strftime('%y')}{month_map[now.month]}FUT"
        gift_ltp = kite.ltp([gift_symbol])
        snapshot["gift_nifty"] = {
            "symbol": gift_symbol,
            "price": gift_ltp.get(gift_symbol, {}).get("last_price"),
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
        conn = sqlite3.connect("dashboard.sqlite")
        cur  = conn.cursor()
        try:
            cur.execute(
                "SELECT strategy_name, symbol, total_return_pct, num_trades "
                "FROM backtest_runs ORDER BY ran_at DESC LIMIT 5"
            )
            rows = cur.fetchall()
            if rows:
                ctx += "\n📈 Recent Backtests:\n"
                for r in rows:
                    ctx += f"  {r[0]} | {r[1]} | Return: {r[2]}% | Trades: {r[3]}\n"
        except Exception:
            pass
        conn.close()
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
    ctx = (
        "You are an expert trading assistant for Indian markets (NSE, BSE, NFO). "
        "You have real-time Zerodha Kite account data below. "
        "Always use exact live numbers for balance/holdings/positions/indices. "
        "If Kite is not connected, say so clearly. "
        "Be concise and actionable. Use ₹ for Indian Rupees.\n\n"
    )
    ctx += build_market_context(snapshot)
    ctx += get_db_context()

    if auto_read:
        for fp in sorted(glob.glob("*.py") + glob.glob("pages/*.py")):
            try:
                ctx += f"\n📄 {fp}:\n```python\n{open(fp).read()[:800]}\n```\n"
            except Exception:
                pass

    if uploaded_files:
        for f in uploaded_files:
            f.seek(0)
            ctx += read_uploaded_file(f)

    return ctx[:14000]


# ── Direct replies (no Claude token used) ────────────────────────────────────
def get_direct_live_reply(prompt: str, snapshot: dict) -> str | None:
    q = prompt.lower().strip()
    live_keywords = [
        "balance", "fund", "funds", "cash", "margin", "holding", "holdings",
        "position", "positions", "nifty", "bank nifty", "sensex", "gift nifty",
        "fin nifty", "midcap", "index", "indices", "portfolio",
    ]

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
