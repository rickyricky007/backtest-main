"""
token_alert_service.py — Daily Kite token expiry alert
=======================================================
Sends Telegram alerts every 20 minutes between 08:30 IST and 09:15 IST
if the Kite access token is missing or invalid.

Behaviour:
    - Toggle (`token_alert_enabled` in app_settings DB) = master switch.
        ON  → alerts active per schedule
        OFF → no alerts ever (permanent until user re-enables)
    - Once a valid token is detected on a given day, alerts stop for the day.
    - Repeats every 20 minutes within the alert window.

Run:
    python token_alert_service.py
    (or via systemd unit `algotrading-token-alert.service`)
"""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path

from alert_engine import send_telegram_message
from app_settings import get_bool
from config import cfg
from logger import get_logger

log = get_logger("token_alert")

# ── Constants ─────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
ALERT_START  = dtime(8, 30)   # 08:30 IST
ALERT_END    = dtime(9, 15)   # 09:15 IST (market open)
ALERT_GAP    = 20 * 60        # 20 minutes between alerts
LOOP_TICK    = 60             # check every 60s
SETTING_KEY  = "token_alert_enabled"
DEFAULT_ON   = True


# ── Token validity check ──────────────────────────────────────────────────────
def is_token_valid() -> bool:
    """Returns True if Kite access token works (lightweight margins() call)."""
    try:
        import kite_data as kd
        kite = kd.kite_client()
        kite.margins()  # lightweight authenticated call
        return True
    except Exception as e:
        log.debug(f"token check failed: {e}")
        return False


# ── Alert window check ────────────────────────────────────────────────────────
def in_alert_window(now_ist: datetime) -> bool:
    """True if current IST time is between 08:30 and 09:15."""
    try:
        t = now_ist.time()
        return ALERT_START <= t <= ALERT_END
    except Exception:
        log.error("in_alert_window failed", exc_info=True)
        return False


# ── Telegram message ──────────────────────────────────────────────────────────
def send_alert(now_ist: datetime) -> bool:
    """Send Telegram alert. Returns True on success."""
    try:
        token   = cfg.telegram_bot_token
        chat_id = cfg.telegram_chat_id
        if not token or not chat_id:
            log.warning("Telegram not configured — skipping alert")
            return False

        msg = (
            "⚠️ <b>Kite Token Expired</b>\n\n"
            "Your Zerodha access token is invalid or missing.\n"
            "Please regenerate it before market opens (09:15 IST).\n\n"
            f"🕐 {now_ist.strftime('%d %b %Y %H:%M:%S IST')}\n\n"
            "Run: <code>python generate_token.py &lt;request_token&gt;</code>\n"
            "Toggle off in Dashboard → System → System Status if not trading today."
        )
        ok = send_telegram_message(token, chat_id, msg)
        if ok:
            log.info("Token alert sent via Telegram")
        else:
            log.error("Telegram send returned False")
        return ok
    except Exception:
        log.error("send_alert failed", exc_info=True)
        return False


# ── Main loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("token_alert_service started")
    last_alert_ts: float = 0.0
    last_valid_date: str = ""   # YYYY-MM-DD when token last seen valid

    while True:
        try:
            now_ist  = datetime.now(IST)
            today    = now_ist.strftime("%Y-%m-%d")

            # 1. Toggle off → idle
            if not get_bool(SETTING_KEY, default=DEFAULT_ON):
                time.sleep(LOOP_TICK)
                continue

            # 2. Outside alert window → idle
            if not in_alert_window(now_ist):
                time.sleep(LOOP_TICK)
                continue

            # 3. Already validated today → idle
            if last_valid_date == today:
                time.sleep(LOOP_TICK)
                continue

            # 4. Token valid? → mark and idle
            if is_token_valid():
                last_valid_date = today
                log.info(f"Token valid for {today} — alerts paused for the day")
                time.sleep(LOOP_TICK)
                continue

            # 5. Token invalid → alert (with 20-min gap)
            now_ts = time.time()
            if now_ts - last_alert_ts >= ALERT_GAP:
                if send_alert(now_ist):
                    last_alert_ts = now_ts

            time.sleep(LOOP_TICK)

        except KeyboardInterrupt:
            log.info("token_alert_service stopped (KeyboardInterrupt)")
            break
        except Exception:
            log.error("Main loop error", exc_info=True)
            time.sleep(LOOP_TICK)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.error("Fatal error in token_alert_service", exc_info=True)
        raise
