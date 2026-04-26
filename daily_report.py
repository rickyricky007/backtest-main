"""
Daily Report — End-of-day P&L summary sent to Telegram at 3:30pm
=================================================================
Queries dashboard.sqlite, builds summary, sends to Telegram.

Usage:
    python daily_report.py           # send now (manual trigger)
    python daily_report.py --loop    # wait until 3:30pm then send (via process_guard)
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, date

from db import read_df
from logger import get_logger
from telegram import send_daily_report, _send
from db_backup import run_backup

log = get_logger("daily_report")

REPORT_HOUR   = 15   # 3pm
REPORT_MINUTE = 30   # :30pm


def build_and_send() -> bool:
    """Query DB, build summary, send Telegram report + trigger backup."""
    try:
        today = date.today().isoformat()
        log.info(f"Building daily report for {today}")

        # ── Strategy trades today ─────────────────────────────────────────────
        trades_df = read_df(
            "SELECT symbol, action, price, pnl, strategy, timestamp "
            "FROM strategy_trades WHERE DATE(timestamp) = ? ORDER BY pnl DESC",
            (today,)
        )

        total_pnl    = float(trades_df["pnl"].sum()) if not trades_df.empty else 0.0
        trade_count  = len(trades_df)
        buy_count    = int((trades_df["action"] == "BUY").sum())  if not trades_df.empty else 0
        sell_count   = int((trades_df["action"] == "SELL").sum()) if not trades_df.empty else 0

        best_trade  = ""
        worst_trade = ""
        if not trades_df.empty:
            best  = trades_df.iloc[0]
            worst = trades_df.iloc[-1]
            best_trade  = f"{best['symbol']} {best['action']} ₹{best['pnl']:+,.0f}"
            worst_trade = f"{worst['symbol']} {worst['action']} ₹{worst['pnl']:+,.0f}"

        # ── Engine orders today ───────────────────────────────────────────────
        orders_df = read_df(
            "SELECT COUNT(*) as cnt, mode FROM engine_orders "
            "WHERE DATE(timestamp) = ? GROUP BY mode",
            (today,)
        )
        signal_count = int(orders_df["cnt"].sum()) if not orders_df.empty else 0

        # ── Detect mode (LIVE takes priority) ─────────────────────────────────
        mode = "PAPER"
        if not orders_df.empty and "LIVE" in orders_df["mode"].values:
            mode = "LIVE"

        # ── Send Telegram ─────────────────────────────────────────────────────
        ok = send_daily_report(
            total_pnl    = total_pnl,
            trade_count  = trade_count,
            signal_count = signal_count,
            buy_count    = buy_count,
            sell_count   = sell_count,
            best_trade   = best_trade,
            worst_trade  = worst_trade,
            mode         = mode,
        )

        # ── Auto-backup DB after report ───────────────────────────────────────
        log.info("Running post-market DB backup...")
        run_backup()

        log.info(f"Daily report sent | P&L: ₹{total_pnl:+,.0f} | Trades: {trade_count}")
        return ok

    except Exception:
        log.error("Daily report failed", exc_info=True)
        _send(
            f"❌ <b>Daily Report FAILED</b>\n"
            f"🕐 {datetime.now().strftime('%d %b %Y %H:%M IST')}\n"
            f"⚠️ Check logs."
        )
        return False


def run_loop() -> None:
    """Wait for 3:30pm IST on weekdays, send report once, then wait for next day."""
    log.info("Daily report scheduler started — will send at 3:30pm IST on weekdays")
    _sent_today: date | None = None

    while True:
        try:
            now     = datetime.now()
            today   = now.date()
            is_weekday = now.weekday() < 5
            is_time    = now.hour == REPORT_HOUR and now.minute >= REPORT_MINUTE

            if is_weekday and is_time and _sent_today != today:
                log.info("3:30pm — sending daily report")
                build_and_send()
                _sent_today = today

            time.sleep(30)   # check every 30 seconds

        except KeyboardInterrupt:
            log.info("Daily report scheduler stopped")
            break
        except Exception:
            log.error("Daily report loop error", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Wait for 3:30pm and send")
    args = parser.parse_args()

    if args.loop:
        run_loop()
    else:
        build_and_send()
