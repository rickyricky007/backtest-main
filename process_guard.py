"""
Watchdog — Auto Restart on Crash
=================================
Keeps these processes alive 24/7:
    1. Streamlit dashboard (app.py)
    2. Strategy engine (strategy_engine.py)
    3. Ticker service (ticker_service.py)

Usage:
    python watchdog.py                    # start all services
    python watchdog.py --service engine   # restart only strategy engine
    python watchdog.py --status           # print process status

Features:
    - Auto-restarts crashed processes within 5 seconds
    - Exponential backoff if a process crashes repeatedly (max 5 min)
    - Logs output to logs/watchdog.log
    - Sends Telegram alert when a service crashes
    - Graceful shutdown on Ctrl+C (SIGINT)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from config import cfg
from telegram import send_startup, send_crash

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
VENV_PY   = BASE_DIR / "venv" / "bin" / "python"
PYTHON    = str(VENV_PY) if VENV_PY.exists() else sys.executable
LOG_DIR   = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

SERVICES = {
    "dashboard": {
        "cmd":      [PYTHON, "-m", "streamlit", "run", str(BASE_DIR / "app.py"),
                     "--server.port=8501", "--server.headless=true"],
        "log":      LOG_DIR / "dashboard.log",
        "max_restarts": 10,
        "restart_delay": 5,   # seconds
    },
    "engine": {
        "cmd":      [PYTHON, str(BASE_DIR / "strategy_engine.py")],
        "log":      LOG_DIR / "engine.log",
        "max_restarts": 20,
        "restart_delay": 3,
    },
    "ticker": {
        "cmd":      [PYTHON, str(BASE_DIR / "ticker_service.py")],
        "log":      LOG_DIR / "ticker.log",
        "max_restarts": 20,
        "restart_delay": 3,
    },
    "token_monitor": {
        "cmd":      [PYTHON, str(BASE_DIR / "token_monitor.py"), "--loop"],
        "log":      LOG_DIR / "token_monitor.log",
        "max_restarts": 20,
        "restart_delay": 10,
    },
    "daily_report": {
        "cmd":      [PYTHON, str(BASE_DIR / "daily_report.py"), "--loop"],
        "log":      LOG_DIR / "daily_report.log",
        "max_restarts": 5,
        "restart_delay": 30,
    },
}

_processes: dict[str, subprocess.Popen] = {}
_crash_counts: dict[str, int] = {s: 0 for s in SERVICES}
_running = True


# ── Telegram ──────────────────────────────────────────────────────────────────

def _alert(msg: str) -> None:
    bot = cfg.telegram_bot_token
    cid = cfg.telegram_chat_id
    if bot and cid:
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot}/sendMessage",
                data={"chat_id": cid, "text": msg, "parse_mode": "Markdown"},
                timeout=5,
            )
        except Exception:
            pass
    _log(f"ALERT: {msg}")


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_DIR / "watchdog.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Process management ────────────────────────────────────────────────────────

def _start(name: str) -> subprocess.Popen:
    svc    = SERVICES[name]
    logf   = open(svc["log"], "a")
    proc   = subprocess.Popen(
        svc["cmd"],
        stdout=logf,
        stderr=logf,
        cwd=str(BASE_DIR),
    )
    _log(f"▶ Started '{name}' (PID {proc.pid})")
    return proc


def _stop(name: str) -> None:
    proc = _processes.get(name)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        _log(f"⏹ Stopped '{name}'")


def _restart(name: str) -> None:
    _stop(name)
    time.sleep(2)
    _processes[name] = _start(name)


def _monitor_loop(services_to_run: list[str]) -> None:
    global _running

    # Start all services
    for name in services_to_run:
        _processes[name] = _start(name)

    _log(f"🐕 Watchdog active — monitoring: {', '.join(services_to_run)}")
    _alert(f"🚀 *Watchdog started*\nMonitoring: {', '.join(services_to_run)}")
    send_startup(services_to_run)

    while _running:
        for name in services_to_run:
            proc = _processes.get(name)
            if proc is None:
                continue

            ret = proc.poll()
            if ret is not None:
                # Process crashed
                _crash_counts[name] += 1
                svc = SERVICES[name]
                delay = min(svc["restart_delay"] * (2 ** min(_crash_counts[name] - 1, 6)), 300)

                _log(f"💥 '{name}' crashed (exit={ret}) — restart #{_crash_counts[name]} in {delay:.0f}s")
                _alert(
                    f"⚠️ *Service crashed:* `{name}`\n"
                    f"Exit code: {ret}\n"
                    f"Restarting in {delay:.0f}s (attempt #{_crash_counts[name]})"
                )
                send_crash(service=name, error=f"exit={ret}", attempt=_crash_counts[name])

                if _crash_counts[name] > svc["max_restarts"]:
                    _log(f"❌ '{name}' crashed too many times ({_crash_counts[name]}x). Giving up.")
                    _alert(f"❌ *{name} gave up after {_crash_counts[name]} crashes.* Manual intervention needed.")
                    services_to_run.remove(name)
                    continue

                time.sleep(delay)
                if _running:
                    _processes[name] = _start(name)
            else:
                # Still running — reset crash counter occasionally
                if _crash_counts[name] > 0:
                    _crash_counts[name] = max(0, _crash_counts[name] - 1)

        time.sleep(5)

    # Shutdown
    _log("🛑 Watchdog shutting down...")
    for name in list(_processes.keys()):
        _stop(name)
    _alert("🛑 *Watchdog stopped.* All services terminated.")


def _print_status() -> None:
    print("\n=== Watchdog Service Status ===")
    for name, svc in SERVICES.items():
        log = svc["log"]
        log_size = f"{log.stat().st_size // 1024}KB" if log.exists() else "no log"
        print(f"  {name:15s} — log: {log} ({log_size})")
    print()


def _handle_signal(sig, frame) -> None:
    global _running
    _log("Received shutdown signal — stopping...")
    _running = False


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    parser = argparse.ArgumentParser(description="Algo trading watchdog")
    parser.add_argument("--service", choices=list(SERVICES.keys()),
                        help="Run only a specific service")
    parser.add_argument("--status",  action="store_true", help="Print service status and exit")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip Streamlit dashboard")
    args = parser.parse_args()

    if args.status:
        _print_status()
        sys.exit(0)

    if args.service:
        services = [args.service]
    elif args.no_dashboard:
        services = ["engine", "ticker"]
    else:
        services = list(SERVICES.keys())

    _monitor_loop(services)
