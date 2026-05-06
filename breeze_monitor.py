"""
Breeze Session Monitor
=======================
Runs as a systemd service on VPS.
- Checks Breeze session every 30 minutes
- Sends Telegram alert when session expires with login URL
- Logs status to journal

Run: python breeze_monitor.py
"""

from __future__ import annotations

import os
import time
import signal
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import breeze_data as bd
import telegram as tg
from logger import get_logger

log = get_logger("breeze_monitor")

CHECK_INTERVAL = 30 * 60   # 30 minutes
_running = True


def _handle_signal(sig, frame):
    global _running
    log.info("Breeze monitor shutting down...")
    _running = False
    sys.exit(0)


def check_breeze_session() -> bool:
    """Returns True if Breeze session is valid."""
    try:
        breeze = bd.breeze_client()
        resp   = breeze.get_funds()
        return resp.get("Status") == 200
    except Exception as e:
        log.warning(f"Breeze session check failed: {e}")
        return False


def send_token_alert():
    """Send Telegram alert with Breeze login URL."""
    api_key   = os.getenv("BREEZE_API_KEY", "")
    login_url = f"https://api.icicidirect.com/apiuser/login?api_key={api_key}"
    msg = (
        "⚠️ *Breeze Session Expired*\n\n"
        "Generate a new session token:\n"
        f"1. Open: {login_url}\n"
        "2. Login with ICICI Direct\n"
        "3. Copy `apisession=` value from redirect URL\n"
        "4. On VPS run:\n"
        "`python breeze_data.py --token YOUR_TOKEN`"
    )
    ok = tg.send_breeze_token_expired(login_url=login_url)
    if ok:
        log.warning("Breeze session expired — Telegram alert sent")
    else:
        log.warning("Breeze session expired — Telegram alert failed")


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("Breeze session monitor started")
    alert_sent = False

    while _running:
        now = datetime.now().strftime("%H:%M")
        if check_breeze_session():
            log.info(f"[{now}] Breeze session OK")
            alert_sent = False
        else:
            log.warning(f"[{now}] Breeze session invalid")
            if not alert_sent:
                send_token_alert()
                alert_sent = True

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
