"""
Telegram Alerts — Unified notification module
=============================================
Single source for ALL Telegram alerts in the system.

Alert types:
    send_signal()       → BUY/SELL signal fired
    send_order()        → Order placed / failed
    send_sl_hit()       → Stop loss triggered
    send_risk_breach()  → Daily loss limit or position limit breached
    send_crash()        → Service crash detected
    send_token_expired()→ Kite token expired mid-day
    send_daily_report() → End-of-day P&L summary (3:30pm)
    send_test()         → Connection test

Usage:
    from telegram import send_signal, send_order, send_crash
    send_signal("RELIANCE", "BUY", score=9, price=2850.0, mode="PAPER")
"""

from __future__ import annotations

from datetime import datetime

import requests

from config import cfg
from logger import get_logger

log = get_logger("telegram")


# ── Alert toggle gate (registry-driven master + per-alert toggles) ────────────
def _gated(alert_id: str) -> bool:
    """
    Returns True if this alert should fire (toggle is ON and master is ON).
    Falls OPEN (allows alert) on any error so we never silently drop alerts.
    """
    try:
        from alert_registry import is_enabled
        return is_enabled(alert_id)
    except Exception:
        log.error(f"_gated check failed for '{alert_id}' — allowing alert", exc_info=True)
        return True


# ── Core sender ───────────────────────────────────────────────────────────────

def _send(message: str) -> bool:
    """Send a Telegram message. Returns True if successful."""
    try:
        token   = cfg.telegram_bot_token
        chat_id = cfg.telegram_chat_id

        if not token or not chat_id:
            log.warning("Telegram not configured — TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing")
            return False

        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )

        if resp.status_code == 200:
            log.debug("Telegram sent OK")
            return True

        log.warning(f"Telegram failed: {resp.status_code} — {resp.text[:100]}")
        return False

    except requests.exceptions.ConnectionError:
        log.warning("Telegram: no internet connection")
        return False
    except Exception:
        log.error("Telegram send error", exc_info=True)
        return False


def _ts() -> str:
    return datetime.now().strftime("%d %b %Y %H:%M:%S IST")


# ── Alert types ───────────────────────────────────────────────────────────────

def send_signal(
    symbol: str,
    action: str,
    score:  int,
    price:  float,
    mode:   str = "PAPER",
) -> bool:
    """BUY or SELL signal fired by confluence engine."""
    try:
        if not _gated("signal"):
            return False
        emoji  = "🟢" if action == "BUY" else "🔴"
        tag    = "📄 PAPER" if mode == "PAPER" else "🔴 LIVE"
        msg = (
            f"{emoji} <b>Signal: {action} {symbol}</b>\n"
            f"💰 Price : ₹{price:,.2f}\n"
            f"📊 Score : {score:+d} / 15\n"
            f"🏷 Mode  : {tag}\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_signal error", exc_info=True)
        return False


def send_order(
    symbol:   str,
    action:   str,
    qty:      int,
    price:    float,
    mode:     str,
    status:   str,
    strategy: str = "",
) -> bool:
    """Order placed or failed."""
    try:
        if not _gated("order"):
            return False
        emoji = "✅" if status == "COMPLETE" else "❌"
        tag   = "📄 PAPER" if mode == "PAPER" else "🔴 LIVE"
        msg = (
            f"{emoji} <b>Order {status}: {action} {symbol}</b>\n"
            f"📦 Qty      : {qty}\n"
            f"💰 Price    : ₹{price:,.2f}\n"
            f"🏷 Mode     : {tag}\n"
            f"⚙️ Strategy : {strategy or '—'}\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_order error", exc_info=True)
        return False


def send_sl_hit(
    symbol:        str,
    trigger_price: float,
    pnl:           float,
    mode:          str = "PAPER",
) -> bool:
    """Stop loss or target triggered."""
    try:
        if not _gated("sl_hit"):
            return False
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        tag       = "📄 PAPER" if mode == "PAPER" else "🔴 LIVE"
        msg = (
            f"🛑 <b>Stop Loss Hit: {symbol}</b>\n"
            f"💥 Trigger : ₹{trigger_price:,.2f}\n"
            f"{pnl_emoji} P&amp;L    : ₹{pnl:+,.2f}\n"
            f"🏷 Mode    : {tag}\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_sl_hit error", exc_info=True)
        return False


def send_risk_breach(
    reason:      str,
    daily_loss:  float,
    limit:       float,
) -> bool:
    """Daily loss limit or position limit breached — CRITICAL."""
    try:
        if not _gated("risk_breach"):
            return False
        msg = (
            f"⚠️ <b>RISK BREACH — Trading Paused</b>\n\n"
            f"❌ Reason      : {reason}\n"
            f"💸 Daily Loss  : ₹{daily_loss:,.2f}\n"
            f"🚧 Limit       : ₹{limit:,.2f}\n\n"
            f"🛑 <b>All new signals blocked until tomorrow.</b>\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_risk_breach error", exc_info=True)
        return False


def send_crash(
    service: str,
    error:   str = "",
    attempt: int = 1,
) -> bool:
    """Service crash detected by process_guard."""
    try:
        if not _gated("crash"):
            return False
        msg = (
            f"💥 <b>Service Crashed: {service}</b>\n"
            f"🔄 Restart attempt #{attempt}\n"
            f"❗ Error : {error[:200] if error else '—'}\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_crash error", exc_info=True)
        return False


def send_token_expired() -> bool:
    """Kite access token expired mid-day."""
    try:
        if not _gated("token_expired"):
            return False
        msg = (
            f"🔑 <b>Kite Token Expired!</b>\n\n"
            f"⚠️ Live data and order placement are now offline.\n\n"
            f"<b>Fix — run in terminal:</b>\n"
            f"1. Get login URL:\n"
            f"<code>python -c \"from kiteconnect import KiteConnect; "
            f"import os; from dotenv import load_dotenv; load_dotenv(); "
            f"k = KiteConnect(api_key=os.getenv('API_KEY')); print(k.login_url())\"</code>\n\n"
            f"2. Login in browser → copy request_token\n\n"
            f"3. Generate token:\n"
            f"<code>python generate_token.py &lt;request_token&gt;</code>\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_token_expired error", exc_info=True)
        return False


def send_breeze_token_expired(login_url: str = "") -> bool:
    """Breeze session expired notification."""
    try:
        if not _gated("token_expired"):
            return False
        login_line = f"1. Open: {login_url}\n" if login_url else "1. Open ICICI Breeze app login URL\n"
        msg = (
            f"🔑 <b>Breeze Session Expired</b>\n\n"
            f"⚠️ Breeze data source is currently unavailable.\n\n"
            f"<b>Fix — run:</b>\n"
            f"{login_line}"
            f"2. Login and copy <code>apisession=</code> value from redirect URL\n"
            f"3. Update token on VPS:\n"
            f"<code>/opt/algotrading/app/venv/bin/python breeze_data.py --token YOUR_TOKEN</code>\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_breeze_token_expired error", exc_info=True)
        return False


def send_daily_report(
    total_pnl:    float,
    trade_count:  int,
    signal_count: int,
    buy_count:    int,
    sell_count:   int,
    best_trade:   str = "",
    worst_trade:  str = "",
    mode:         str = "PAPER",
) -> bool:
    """End-of-day P&L summary sent at 3:30pm."""
    try:
        if not _gated("daily_report"):
            return False
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
        tag       = "📄 PAPER" if mode == "PAPER" else "🔴 LIVE"
        msg = (
            f"📊 <b>Daily Report — {datetime.now().strftime('%d %b %Y')}</b>\n\n"
            f"{pnl_emoji} <b>Total P&amp;L : ₹{total_pnl:+,.2f}</b>\n\n"
            f"📈 Signals   : {signal_count} (🟢{buy_count} BUY / 🔴{sell_count} SELL)\n"
            f"✅ Trades    : {trade_count}\n"
            f"🏷 Mode      : {tag}\n"
        )
        if best_trade:
            msg += f"🏆 Best      : {best_trade}\n"
        if worst_trade:
            msg += f"💀 Worst     : {worst_trade}\n"
        msg += f"\n🕐 Market closed — {_ts()}"
        return _send(msg)
    except Exception:
        log.error("send_daily_report error", exc_info=True)
        return False


def send_startup(services: list[str]) -> bool:
    """System started — sent by process_guard on launch."""
    try:
        if not _gated("startup"):
            return False
        msg = (
            f"🚀 <b>Algo Trading System Started</b>\n\n"
            f"✅ Services: {', '.join(services)}\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_startup error", exc_info=True)
        return False


def send_test() -> bool:
    """Test Telegram connection."""
    try:
        msg = (
            f"✅ <b>Telegram Connected!</b>\n"
            f"Algo Trading System alerts are working.\n"
            f"🕐 {_ts()}"
        )
        return _send(msg)
    except Exception:
        log.error("send_test error", exc_info=True)
        return False


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ok = send_test()
    print("✅ Telegram working" if ok else "❌ Telegram failed — check .env")
