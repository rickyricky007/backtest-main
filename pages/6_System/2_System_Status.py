"""
System Status — Control Room
=============================
One-stop view for:
    - Kite API connection health
    - Ticker service status (live/stale)
    - Strategy engine status
    - Log file tail
    - Token expiry countdown
    - Service start/stop controls (paper mode)
    - DB stats (trade count, size)
    - Quick terminal command reference
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

import kite_data as kd
from alert_registry import (
    ALERTS, MASTER_KEY, MASTER_DEFAULT,
    list_by_category, status_summary,
    is_master_enabled, set_master_enabled,
    set_enabled,
)
from app_settings import get_bool, set_bool
from auth_streamlit import render_sidebar_kite_session
from db import count
from logger import get_logger

log = get_logger("system_status_page")

BASE_DIR = Path(__file__).parent.parent
LOG_DIR  = BASE_DIR / "logs"

# ── helpers ───────────────────────────────────────────────────────────────────

def _token_info() -> dict:
    f = BASE_DIR / "access_token.json"
    if not f.exists():
        return {"valid": False, "date": None, "token": None}
    try:
        d = json.loads(f.read_text())
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "valid": d.get("date") == today,
            "date":  d.get("date"),
            "token": d.get("access_token", "")[:10] + "...",
        }
    except Exception:
        return {"valid": False, "date": None, "token": None}


def _kite_ping() -> bool:
    try:
        kite = kd.kite_client()
        kite.profile()
        return True
    except Exception:
        return False


def _ticker_status() -> dict:
    f = BASE_DIR / "ticker_data.json"
    if not f.exists():
        return {"running": False, "stale": True, "last_update": None, "symbols": []}
    try:
        data    = json.loads(f.read_text())
        now     = datetime.now().timestamp()
        updates = [v.get("updated_at", 0) for v in data.values() if isinstance(v, dict)]
        last    = max(updates) if updates else 0
        stale   = (now - last) > 15
        return {
            "running":     not stale,
            "stale":       stale,
            "last_update": datetime.fromtimestamp(last).strftime("%H:%M:%S") if last else "Never",
            "symbols":     list(data.keys()),
            "age_s":       round(now - last, 1) if last else 9999,
        }
    except Exception:
        return {"running": False, "stale": True, "last_update": "Error", "symbols": []}


def _log_tail(log_name: str, n: int = 30) -> str:
    log_file = LOG_DIR / f"{log_name}.log"
    if not log_file.exists():
        return f"[{log_name}.log not found — start the service first]"
    try:
        lines = log_file.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"Error reading log: {e}"


def _db_stats() -> dict:
    try:
        return {
            "size_kb":      "☁️ Supabase",
            "trades":       count("strategy_trades"),
            "orders":       count("engine_orders"),
            "journal":      count("trade_journal"),
            "sl_positions": count("sl_positions"),
        }
    except Exception:
        return {"size_kb": "—", "trades": 0, "orders": 0, "journal": 0, "sl_positions": 0}


def _process_running(name: str) -> bool:
    """Check if a process with script name 'name' is running."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", name], capture_output=True, text=True
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


# ── UI ────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="System Status", page_icon="🖥️", layout="wide")
render_sidebar_kite_session()
st.title("🖥️ System Status — Control Room")

# ── 1. Health checks ──────────────────────────────────────────────────────────
st.subheader("🩺 Health Checks")

token = _token_info()
ticker = _ticker_status()

col1, col2, col3, col4 = st.columns(4)

with col1:
    if token["valid"]:
        st.success("🟢 Kite Token — Valid")
        st.caption(f"Date: {token['date']}  |  Token: {token['token']}")
    else:
        st.error("🔴 Kite Token — Invalid / Missing")
        if token["date"]:
            st.caption(f"Last token date: {token['date']} (stale)")
        else:
            st.caption("No token found. Run `python generate_token.py`")

with col2:
    with st.spinner("Pinging Kite API..."):
        kite_ok = _kite_ping()
    if kite_ok:
        st.success("🟢 Kite API — Connected")
        st.caption("Profile endpoint responding")
    else:
        st.error("🔴 Kite API — Disconnected")
        st.caption("Check token and internet connection")

with col3:
    if ticker["running"]:
        st.success(f"🟢 Ticker — Live")
        st.caption(f"Last tick: {ticker['last_update']} ({ticker['age_s']}s ago)")
    else:
        st.warning(f"🟡 Ticker — {'Stale' if ticker['last_update'] != 'Never' else 'Not Started'}")
        st.caption(f"Last: {ticker['last_update']} | Run: `python ticker_service.py`")

with col4:
    engine_running = _process_running("strategy_engine.py")
    if engine_running:
        st.success("🟢 Strategy Engine — Running")
    else:
        st.warning("🟡 Strategy Engine — Stopped")
        st.caption("Run: `python strategy_engine.py`")

st.divider()

# ── 1.5 ONE-STOP ALERT CONTROL PANEL ─────────────────────────────────────────
st.subheader("🔔 Alert Control Panel")
st.caption(
    "Master kill switch + per-alert toggles. All toggles are DB-persisted — they survive restarts. "
    "New alert types added to `alert_registry.py` show up here automatically."
)

try:
    summary = status_summary()
    master_on = summary["master_enabled"]

    # ── Master kill switch ───────────────────────────────────────────────────
    mc1, mc2, mc3 = st.columns([2, 1, 1])
    with mc1:
        new_master = st.toggle(
            "🚨 **MASTER ALERT SWITCH** — overrides all individual toggles below",
            value=master_on,
            key="master_alert_toggle",
            help="OFF = ALL Telegram alerts silenced (regardless of individual toggles below). "
                 "ON = individual toggles take effect. Useful for vacations, market holidays, debugging.",
        )
        if new_master != master_on:
            set_master_enabled(new_master)
            st.success(f"Master switch {'ON' if new_master else 'OFF'} — saved.")
            st.rerun()

    with mc2:
        st.metric("Enabled", summary["enabled_count"])
    with mc3:
        st.metric("Disabled", summary["disabled_count"])

    if not master_on:
        st.error("🚨 Master switch is **OFF** — no alerts will fire from anywhere in the system. "
                 "Individual toggles below are paused.")

    st.markdown("---")

    # ── Per-alert toggles, grouped by category ───────────────────────────────
    grouped = list_by_category()

    # Render two categories per row
    cat_emoji = {
        "Trading":  "💹",
        "Risk":     "⚠️",
        "System":   "🖥️",
        "Schedule": "📅",
        "Reports":  "📊",
        "Manual":   "👤",
    }

    cats_with_items = [(c, items) for c, items in grouped.items() if items]
    for i in range(0, len(cats_with_items), 2):
        cols = st.columns(2)
        for j, (cat, items) in enumerate(cats_with_items[i:i+2]):
            with cols[j]:
                st.markdown(f"### {cat_emoji.get(cat, '🔔')} {cat}")
                for alert_id, defn, current_state in items:
                    new_state = st.toggle(
                        defn.label,
                        value=current_state,
                        key=f"alert_toggle_{alert_id}",
                        help=defn.description,
                        disabled=not master_on,
                    )
                    if new_state != current_state:
                        if set_enabled(alert_id, new_state):
                            st.toast(
                                f"{'Enabled' if new_state else 'Disabled'}: {defn.label}",
                                icon="✅" if new_state else "🔕",
                            )
                            st.rerun()

    st.markdown("---")

    # ── Service health for the daily token-alert background loop ─────────────
    alert_proc = _process_running("token_alert_service.py")
    icon = "🟢" if alert_proc else "🔴"
    st.caption(
        f"{icon} **token_alert_service**: {'Running' if alert_proc else 'Stopped'} — "
        "start with `sudo systemctl start algotrading-token-alert` (EC2) or "
        "`python token_alert_service.py` (local). "
        "Other alerts fire from telegram.py directly — no separate service needed."
    )

    with st.expander("ℹ️ How to add a new alert in the future"):
        st.markdown("""
**3 steps — no UI changes needed.**

1. **Add an entry in `alert_registry.py`** (one line in the `ALERTS` dict):
   ```python
   "my_new_alert": AlertDef(
       key="alert_my_new_alert_enabled",
       label="My new alert",
       description="What this alert does.",
       default_on=True,
       category="Trading",   # or Risk / System / Schedule / Reports / Manual
   ),
   ```

2. **In your alert-sending function**, gate it:
   ```python
   from alert_registry import is_enabled
   if not is_enabled("my_new_alert"):
       return False
   # ... your send logic
   ```

3. **Reload this page** — your new toggle appears in the right category. Done.
        """)

except Exception as e:
    log.error("Alert panel render failed", exc_info=True)
    st.error(f"Alert panel error: {e}")

st.divider()

# ── 2. DB Stats ───────────────────────────────────────────────────────────────
st.subheader("🗄️ Database")

db = _db_stats()
d1, d2, d3, d4, d5 = st.columns(5)
d1.metric("DB Size", f"{db.get('size_kb', 0)} KB")
d2.metric("Strategy Trades", db.get("trades", 0))
d3.metric("Orders", db.get("orders", 0))
d4.metric("Journal Entries", db.get("journal", 0))
d5.metric("SL Positions", db.get("sl_positions", 0))

st.divider()

# ── 3. Process status ─────────────────────────────────────────────────────────
st.subheader("⚙️ Processes")

procs = {
    "Streamlit Dashboard": "streamlit",
    "Strategy Engine":     "strategy_engine.py",
    "Ticker Service":      "ticker_service.py",
    "Process Guard":       "process_guard.py",
    "Scheduler":           "scheduler.py",
    "Auto Renew Token":    "auto_renew_token.py",
    "Token Alert Service": "token_alert_service.py",
}

proc_cols = st.columns(3)
for i, (label, script) in enumerate(procs.items()):
    with proc_cols[i % 3]:
        running = _process_running(script)
        icon    = "🟢" if running else "🔴"
        st.markdown(f"{icon} **{label}**")
        st.caption("Running" if running else "Stopped")

st.divider()

# ── 4. Log Viewer ─────────────────────────────────────────────────────────────
st.subheader("📜 Log Viewer")

log_choice = st.selectbox(
    "Select log",
    ["watchdog", "scheduler", "engine", "ticker", "dashboard"],
)
n_lines = st.slider("Lines to show", 10, 200, 50)
log_text = _log_tail(log_choice, n_lines)
st.code(log_text, language="text")

if st.button("🔄 Refresh Log"):
    st.rerun()

st.divider()

# ── 5. Quick Command Reference ────────────────────────────────────────────────
st.subheader("⌨️ Terminal Commands")

cmds = {
    "Generate Kite Token":    "python generate_token.py",
    "Start Dashboard":        "streamlit run app.py",
    "Start Ticker Service":   "python ticker_service.py",
    "Start Strategy Engine":  "python strategy_engine.py",
    "Start Process Guard (all)":   "python process_guard.py",
    "Process Guard (no dashboard)":"python process_guard.py --no-dashboard",
    "Start Scheduler":        "python scheduler.py",
    "Run Backtest":           "python backtest_runner.py",
    "Token Check":            "python auto_renew_token.py --status",
    "Scheduler Dry Run":      "python scheduler.py --dry-run",
}

cmd_cols = st.columns(2)
for i, (label, cmd) in enumerate(cmds.items()):
    with cmd_cols[i % 2]:
        st.markdown(f"**{label}**")
        st.code(f"cd ~/algo_trading/ricky_1 && {cmd}", language="bash")

st.divider()

# ── 6. Architecture overview ──────────────────────────────────────────────────
st.subheader("🏗️ System Architecture")
st.markdown("""
```
┌─────────────────────────────────────────────────────────┐
│                    ZERODHA KITE API                     │
│         REST (orders/data)  +  WebSocket (ticks)        │
└────────────┬───────────────────────┬────────────────────┘
             │                       │
    ┌─────────▼──────┐    ┌──────────▼─────────┐
    │  kite_data.py  │    │  ticker_service.py  │
    │  REST wrapper  │    │  WebSocket → JSON   │
    └─────────┬──────┘    └──────────┬──────────┘
              │                      │ ticker_data.json
    ┌─────────▼──────────────────────▼──────────────┐
    │              strategy_engine.py                │
    │  BaseStrategy → Signal → OrderManager → Kite  │
    │  + StopLossManager + RiskManager + Alerts     │
    └──────────────────┬─────────────────────────────┘
                       │
              ┌────────▼────────┐
              │  dashboard.sqlite│  (all trades, orders, SL)
              └────────┬────────┘
                       │
    ┌──────────────────▼──────────────────────────────┐
    │         Streamlit Dashboard (app.py)             │
    │  Overview / Options Chain / F&O / PnL / Journal │
    └─────────────────────────────────────────────────┘
                       │
    ┌──────────────────▼──────────────────────────────┐
    │    Infrastructure                                │
    │  watchdog.py + scheduler.py + auto_renew_token  │
    └─────────────────────────────────────────────────┘
```
""")

st.caption(f"Status refreshed at {datetime.now().strftime('%H:%M:%S')}")
if st.button("🔄 Refresh Status"):
    st.rerun()
