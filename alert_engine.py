"""Alert engine — Telegram notifications for price and P&L alerts.

All Telegram sends route through send_telegram_message() — which respects
the master alert switch in alert_registry. When master switch is OFF, ALL
Telegram traffic from this function is suppressed.

Optional alert_id parameter checks per-alert toggle too.
"""

from __future__ import annotations

from datetime import datetime

import requests

from dotenv import load_dotenv
import os

from logger import get_logger

log = get_logger("alert_engine")


# ── Master-switch gate (lazy import to avoid circular dependencies) ───────
def _allowed(alert_id: str | None = None) -> bool:
    """
    Returns False when master switch is OFF, OR when a known alert_id is OFF.
    Returns True (fail-open) on registry errors so we never silently drop.
    """
    try:
        from alert_registry import is_master_enabled, is_enabled
        if not is_master_enabled():
            return False
        if alert_id:
            return is_enabled(alert_id)
        return True
    except Exception:
        log.error(f"_allowed check failed for '{alert_id}' — allowing send", exc_info=True)
        return True


# ── Telegram ───────────────────────────────────────────────────────────────

def send_telegram_message(
    token: str,
    chat_id: str,
    message: str,
    alert_id: str | None = None,
) -> bool:
    """
    Send a message via Telegram bot. Returns True if successful.
    
    alert_id: optional alert_registry key (e.g. "signal", "price_alert").
              If provided, respects per-alert toggle. Always respects master switch.
    """
    try:
        if not _allowed(alert_id):
            log.info(f"Telegram suppressed by alert toggle (alert_id={alert_id})")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        log.error("send_telegram_message failed", exc_info=True)
        return False


def test_telegram_connection(token: str, chat_id: str) -> tuple[bool, str]:
    """Send a test message. Returns (success, message)."""
    msg = (
        "✅ <b>Telegram Alert Connected!</b>\n"
        "Your F&O Paper Trading dashboard is now connected.\n"
        f"Time: {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
    )
    ok = send_telegram_message(token, chat_id, msg)
    if ok:
        return True, "Test message sent successfully!"
    return False, "Failed to send. Check your Token and Chat ID."


# ── Condition Check ────────────────────────────────────────────────────────

def check_condition(current_value: float, condition: str, target_value: float) -> bool:
    """Check if alert condition is met."""
    if condition == "ABOVE":
        return current_value >= target_value
    elif condition == "BELOW":
        return current_value <= target_value
    return False


# ── Message Formatters ─────────────────────────────────────────────────────

def format_price_alert_message(
    display_name: str,
    condition: str,
    target: float,
    current: float,
) -> str:
    direction = "🔼" if condition == "ABOVE" else "🔽"
    return (
        f"🔔 <b>Price Alert Triggered!</b>\n\n"
        f"📌 Symbol: <b>{display_name}</b>\n"
        f"{direction} Condition: Price {condition} ₹{target:,.2f}\n"
        f"💰 Current Price: <b>₹{current:,.2f}</b>\n\n"
        f"🕐 {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
    )


def format_pnl_alert_message(
    condition: str,
    target: float,
    current: float,
) -> str:
    emoji = "🟢" if current >= 0 else "🔴"
    direction = "🔼" if condition == "ABOVE" else "🔽"
    return (
        f"🔔 <b>P&L Alert Triggered!</b>\n\n"
        f"{direction} Condition: P&L {condition} ₹{target:,.2f}\n"
        f"{emoji} Current P&L: <b>₹{current:,.2f}</b>\n\n"
        f"🕐 {datetime.now().strftime('%d %b %Y %H:%M:%S')}"
    )
# ── Test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    ok, msg = test_telegram_connection(TOKEN, CHAT_ID)
    print(msg)