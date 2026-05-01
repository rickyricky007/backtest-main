"""
Auto Token Renewal
==================
Sends a Telegram/email reminder at 8:45 AM every trading day to renew the
Kite access token. Also validates if today's token is still valid.

Usage:
    python auto_renew_token.py          # one-shot check
    python auto_renew_token.py --loop   # loop daily (for server deployment)

How it works:
    1. At 08:45 IST every trading day, sends you a Telegram message with
       the Kite login URL so you can generate a fresh token quickly.
    2. After 09:15 (market open), validates the token by pinging Kite profile API.
    3. If token is stale (yesterday's), marks it invalid and alerts again.

To automate (macOS LaunchAgent or Linux cron):
    # crontab -e
    45 8 * * 1-5 /path/to/venv/bin/python /path/to/auto_renew_token.py
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests
from config import cfg

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
TOKEN_FILE   = BASE_DIR / "access_token.json"

KITE_API_KEY   = cfg.kite_api_key
TG_BOT_TOKEN   = cfg.telegram_bot_token
TG_CHAT_ID     = cfg.telegram_chat_id
KITE_LOGIN_URL = cfg.kite_login_url


# ── Telegram helper ───────────────────────────────────────────────────────────

def _send_telegram(msg: str) -> bool:
    # Master kill switch (registry-driven) — when OFF, suppress all Telegram
    try:
        from alert_registry import is_master_enabled
        if not is_master_enabled():
            print("[AutoRenew] Telegram suppressed by master alert switch")
            return False
    except Exception:
        pass  # registry unavailable — proceed (don't silently drop critical token alerts)

    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("[AutoRenew] Telegram not configured — printing instead:")
        print(msg)
        return False
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": TG_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        }, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"[AutoRenew] Telegram error: {e}")
        return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def _load_token() -> dict | None:
    if not TOKEN_FILE.is_file():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except Exception:
        return None


def _token_is_today(token_data: dict | None) -> bool:
    if not token_data:
        return False
    saved_date = token_data.get("date", "")
    return saved_date == datetime.now().strftime("%Y-%m-%d")


def _validate_token(access_token: str) -> bool:
    """Ping Kite profile endpoint to validate token."""
    if not access_token or not KITE_API_KEY:
        return False
    try:
        resp = requests.get(
            "https://api.kite.trade/user/profile",
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {KITE_API_KEY}:{access_token}",
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Main logic ────────────────────────────────────────────────────────────────

def check_and_alert() -> None:
    """Run a single token validity check and alert if needed."""
    now  = datetime.now()
    data = _load_token()

    if _token_is_today(data):
        token = data.get("access_token", "")
        valid = _validate_token(token)
        if valid:
            print(f"[AutoRenew] ✅ Token is valid for today ({now.date()})")
            return
        else:
            msg = (
                f"⚠️ *Kite Token Expired*\n"
                f"Today's token failed validation at {now.strftime('%H:%M')}.\n"
                f"Please generate a fresh token:\n"
                f"1️⃣ Open: {KITE_LOGIN_URL}\n"
                f"2️⃣ Login and get the `request_token` from the redirect URL\n"
                f"3️⃣ Run: `python generate_token.py`"
            )
    else:
        msg = (
            f"🔑 *Kite Token Renewal Required*\n"
            f"Good morning! Market opens at 09:15.\n"
            f"Please renew your access token now:\n\n"
            f"1️⃣ Open: {KITE_LOGIN_URL}\n"
            f"2️⃣ Login → copy `request_token` from URL\n"
            f"3️⃣ Run: `python generate_token.py`\n\n"
            f"_Auto-reminder from your algo trading system_ 🤖"
        )

    print(f"[AutoRenew] Sending alert: {msg[:80]}...")
    _send_telegram(msg)


def loop_daily() -> None:
    """Run in a loop — sends alert at 08:45 each weekday."""
    print("[AutoRenew] Running in loop mode. Ctrl+C to stop.")
    alerted_today = ""

    while True:
        now  = datetime.now()
        today = now.strftime("%Y-%m-%d")
        weekday = now.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun

        # Only on weekdays
        if weekday < 5:
            # Alert at 08:45
            if now.hour == 8 and now.minute >= 45 and alerted_today != today:
                print(f"[AutoRenew] {now.strftime('%H:%M')} — Running token check...")
                check_and_alert()
                alerted_today = today

            # Re-check at 09:20 (after market open) to confirm token is valid
            if now.hour == 9 and now.minute >= 20:
                data = _load_token()
                if not _token_is_today(data):
                    _send_telegram(
                        "❌ *Market is OPEN but no valid Kite token found!*\n"
                        "Run `python generate_token.py` immediately."
                    )

        time.sleep(60)  # check every minute


# ── cron-safe status writer ───────────────────────────────────────────────────

def write_status() -> None:
    """Write token status to a file (for monitoring dashboards)."""
    data  = _load_token()
    valid = _token_is_today(data) and _validate_token(data.get("access_token", "") if data else "")
    status = {
        "valid": valid,
        "date": data.get("date", "") if data else "",
        "checked_at": datetime.now().isoformat(),
    }
    status_file = BASE_DIR / "token_status.json"
    status_file.write_text(json.dumps(status, indent=2))
    print(f"[AutoRenew] Status: {'✅ Valid' if valid else '❌ Invalid'} — written to token_status.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kite token auto-renewal helper")
    parser.add_argument("--loop", action="store_true", help="Run continuously (for server)")
    parser.add_argument("--status", action="store_true", help="Write status JSON and exit")
    args = parser.parse_args()

    if args.status:
        write_status()
    elif args.loop:
        loop_daily()
    else:
        check_and_alert()
