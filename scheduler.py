"""
Scheduler — Scheduled Jobs for Algo Trading
============================================
Runs time-based jobs:
    08:45  → Token renewal reminder (Telegram)
    09:10  → Pre-market checks (token valid, strategy engine alive)
    09:15  → Market open: activate strategies, start tickers
    15:30  → Market close: deactivate strategies, run EOD report
    15:45  → Send Telegram P&L summary
    16:00  → Backup database, rotate logs
    18:00  → Run backtest on today's data (optional)

Usage:
    python scheduler.py          # runs all jobs (blocking)
    python scheduler.py --dry-run # shows what would run

Safe to run alongside process_guard.py — they are independent.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path

import requests
from alert_registry import is_enabled
from config import cfg
from db import read_df

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
LOG_DIR   = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"
LOG_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

VENV_PY  = BASE_DIR / "venv" / "bin" / "python"
PYTHON   = str(VENV_PY) if VENV_PY.exists() else sys.executable


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_DIR / "scheduler.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _send_telegram(msg: str) -> None:
    """Defense-in-depth: also gate at sender level (jobs already gate on alert_id)."""
    try:
        from alert_registry import is_master_enabled
        if not is_master_enabled():
            _log(f"Scheduler Telegram suppressed by master switch: {msg[:80]}")
            return
    except Exception:
        pass  # registry unavailable — proceed (don't silently drop)

    bot = cfg.telegram_bot_token
    cid = cfg.telegram_chat_id
    if not bot or not cid:
        _log(f"Telegram not configured. Message: {msg[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            data={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        _log(f"Telegram error: {e}")


def _is_market_day() -> bool:
    """Check if today is a weekday (Mon–Fri). Doesn't account for NSE holidays."""
    return datetime.now().weekday() < 5


def _run_script(script: str, args: list[str] | None = None) -> int:
    """Run a Python script and return exit code."""
    cmd = [PYTHON, str(BASE_DIR / script)] + (args or [])
    try:
        result = subprocess.run(cmd, cwd=str(BASE_DIR), timeout=60)
        return result.returncode
    except Exception as e:
        _log(f"Script {script} error: {e}")
        return -1


# ── Jobs ──────────────────────────────────────────────────────────────────────

def job_token_reminder() -> None:
    """08:45 — Remind to renew Kite token."""
    _log("JOB: token_reminder")
    _run_script("auto_renew_token.py")


def job_premarket_check() -> None:
    """09:10 — Validate token is ready before market open."""
    _log("JOB: premarket_check")
    if not is_enabled("pre_market_check"):
        _log("pre_market_check alert disabled — skipping Telegram")
        return

    # Real Kite token file is `.kite_access_token` (plain text)
    token_file = BASE_DIR / ".kite_access_token"
    if not token_file.exists() or not token_file.read_text().strip():
        _send_telegram(
            "❌ *Pre-market Alert*: No Kite access token found!\n"
            "Market opens in 5 minutes — run `python generate_token.py <request_token>` now!"
        )
        return

    # Validate token actually works (lightweight kite.profile() call)
    try:
        import kite_data as kd
        kd.kite_client().profile()
        _log("Token is fresh and valid for today. ✅")
        _send_telegram("✅ *Pre-market check passed.* Token valid. Strategies starting at 09:15.")
    except Exception as e:
        _send_telegram(
            f"⚠️ *Pre-market Alert*: Token validation failed — {e}\n"
            "Please renew before 09:15."
        )


def job_market_open() -> None:
    """09:15 — Market open: strategies should be live via watchdog."""
    _log("JOB: market_open")
    if not is_enabled("market_open"):
        _log("market_open alert disabled — skipping Telegram")
        return
    _send_telegram(
        "🔔 *Market OPEN* (09:15 IST)\n"
        "Strategies are active. Ticker running. Good luck! 📈"
    )


def job_market_close() -> None:
    """15:30 — Market close."""
    _log("JOB: market_close")
    if is_enabled("market_close"):
        _send_telegram("🔔 *Market CLOSED* (15:30 IST). Generating EOD report...")
    else:
        _log("market_close alert disabled — skipping ping")
    # Give strategies time to exit positions
    time.sleep(30)
    job_eod_report()


def job_eod_report() -> None:
    """15:45 — Send P&L summary to Telegram."""
    _log("JOB: eod_report")
    if not is_enabled("daily_report"):
        _log("daily_report alert disabled — skipping Telegram EOD report")
        return
    try:
        today = date.today().strftime("%Y-%m-%d")

        # Today's trades from Supabase
        df = read_df(
            "SELECT strategy, pnl FROM strategy_trades WHERE DATE(timestamp) = %s",
            (today,)
        )

        if df.empty:
            _send_telegram(f"📊 *EOD Report — {today}*\nNo trades today.")
            return

        trades_df_raw = list(df.itertuples(index=False))
        total_pnl = df["pnl"].sum()
        n_trades  = len(df)
        wins      = (df["pnl"] > 0).sum()
        win_rate  = round(wins / n_trades * 100, 1) if n_trades else 0

        # Per-strategy
        strat_pnl = df.groupby("strategy")["pnl"].sum().to_dict()

        strat_lines = "\n".join(
            f"  `{s}`: {'+'if p>=0 else ''}₹{p:,.0f}"
            for s, p in sorted(strat_pnl.items(), key=lambda x: -x[1])
        )

        emoji = "🟢" if total_pnl >= 0 else "🔴"
        msg = (
            f"{emoji} *EOD Report — {today}*\n\n"
            f"*Total P&L:* {'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}\n"
            f"*Trades:* {n_trades}  |  *Win Rate:* {win_rate}%\n\n"
            f"*By Strategy:*\n{strat_lines}"
        )
        _send_telegram(msg)
    except Exception as e:
        _log(f"EOD report error: {e}")
        _send_telegram(f"⚠️ EOD report failed: {e}")


def job_backup_db() -> None:
    """16:00 — DB is now in Supabase (cloud). Log confirmation."""
    _log("JOB: backup_db — data stored in Supabase, no local backup needed ✅")


def job_rotate_logs() -> None:
    """16:00 — Rotate large log files."""
    _log("JOB: rotate_logs")
    for log_file in LOG_DIR.glob("*.log"):
        if log_file.stat().st_size > 10 * 1024 * 1024:  # 10 MB
            ts   = datetime.now().strftime("%Y%m%d")
            arch = log_file.with_name(f"{log_file.stem}_{ts}.log.bak")
            shutil.move(str(log_file), str(arch))
            _log(f"Rotated {log_file.name} → {arch.name}")


# ── Schedule definition ───────────────────────────────────────────────────────

# (hour, minute): (job_function, description)
SCHEDULE: list[tuple[int, int, callable, str]] = [
    (8,  45, job_token_reminder,  "Token renewal reminder"),
    (9,  10, job_premarket_check, "Pre-market token check"),
    (9,  15, job_market_open,     "Market open alert"),
    (15, 30, job_market_close,    "Market close + EOD report"),
    (16, 0,  job_backup_db,       "Backup database"),
    (16, 0,  job_rotate_logs,     "Rotate logs"),
]


def _main(dry_run: bool = False) -> None:
    _log("⏰ Scheduler started" + (" (DRY RUN)" if dry_run else ""))

    if dry_run:
        print("\nScheduled jobs:")
        for h, m, fn, desc in SCHEDULE:
            print(f"  {h:02d}:{m:02d}  {desc}")
        return

    fired_today: set[str] = set()

    while True:
        now   = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Reset at midnight
        if now.hour == 0 and now.minute == 0:
            fired_today.clear()

        if not _is_market_day():
            time.sleep(60)
            continue

        for h, m, fn, desc in SCHEDULE:
            key = f"{today}-{h:02d}{m:02d}-{fn.__name__}"
            if now.hour == h and now.minute == m and key not in fired_today:
                _log(f"⚡ Running job: {desc}")
                try:
                    fn()
                except Exception as e:
                    _log(f"Job '{desc}' error: {e}")
                finally:
                    fired_today.add(key)

        time.sleep(30)  # check every 30 seconds


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Algo trading scheduler")
    parser.add_argument("--dry-run", action="store_true", help="Show schedule and exit")
    args = parser.parse_args()
    _main(dry_run=args.dry_run)
