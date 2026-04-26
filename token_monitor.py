"""
Token Monitor — Detect expired Kite token, alert on Telegram
=============================================================
Runs as a background check. If token is expired or missing,
sends Telegram alert immediately with fix instructions.

Usage:
    python token_monitor.py          # check once
    python token_monitor.py --loop   # check every 5 min (run via process_guard)
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

import kite_data as kd
from logger import get_logger
from telegram import send_token_expired

log = get_logger("token_monitor")

CHECK_INTERVAL = 300   # 5 minutes
_alert_sent    = False  # send alert only once per expiry, not every 5 min


def check_token() -> bool:
    """Returns True if token is valid, False if expired/missing."""
    try:
        token = kd.load_access_token()
        if not token:
            log.warning("No access token found")
            return False

        # Try a lightweight Kite API call to verify token is live
        kite = kd.kite_client()
        if not kite:
            return False

        kite.profile()   # lightweight — just fetches user profile
        log.debug("Token valid ✅")
        return True

    except Exception as e:
        err = str(e).lower()
        if "token" in err or "invalid" in err or "auth" in err or "403" in err:
            log.warning(f"Token expired or invalid: {e}")
            return False
        # Network error etc — don't alert
        log.debug(f"Token check inconclusive: {e}")
        return True


def run_once() -> None:
    valid = check_token()
    if not valid:
        log.error("❌ Token expired — sending Telegram alert")
        send_token_expired()
        print("❌ Token expired — Telegram alert sent")
    else:
        print("✅ Token valid")


def run_loop() -> None:
    """Continuously check token every CHECK_INTERVAL seconds."""
    global _alert_sent
    log.info(f"Token monitor started — checking every {CHECK_INTERVAL}s")

    while True:
        try:
            now = datetime.now()

            # Only check during market hours (8am–4pm IST) on weekdays
            if now.weekday() < 5 and 8 <= now.hour < 16:
                valid = check_token()

                if not valid and not _alert_sent:
                    log.error("❌ Token expired — sending Telegram alert")
                    send_token_expired()
                    _alert_sent = True   # don't spam — alert once per expiry

                elif valid and _alert_sent:
                    # Token was renewed — reset flag
                    _alert_sent = False
                    log.info("✅ Token renewed — monitoring resumed")

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Token monitor stopped")
            break
        except Exception:
            log.error("Token monitor error", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    args = parser.parse_args()

    if args.loop:
        run_loop()
    else:
        run_once()
