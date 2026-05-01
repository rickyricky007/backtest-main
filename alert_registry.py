"""
alert_registry.py — One-stop registry + toggle for ALL Telegram alerts
======================================================================
Every Telegram alert in the system gates itself on `is_enabled(alert_id)`.
Toggles are persisted in the `app_settings` table (DB-backed, survives restarts).

To add a NEW alert in the future:
    1. Register it in ALERTS dict below (one line)
    2. In your alert function, add `if not is_enabled("your_id"): return False`
    3. Toggle appears in System Status page automatically — no UI code changes.

Usage:
    from alert_registry import is_enabled

    def send_my_alert():
        if not is_enabled("signal"):
            return False
        # ... actual send logic

User-facing UI: pages/6_System/2_System_Status.py renders ALL toggles dynamically
from this registry, grouped by category, plus a master kill switch.
"""

from __future__ import annotations

from dataclasses import dataclass

from app_settings import get_bool, set_bool
from logger import get_logger

log = get_logger("alert_registry")

# ── Categories (controls UI grouping) ─────────────────────────────────────────
CATEGORIES = ["Trading", "Risk", "System", "Schedule", "Reports", "Manual"]


@dataclass
class AlertDef:
    """Definition of a single alert type."""
    key:         str   # storage key in app_settings table
    label:       str   # short label shown in UI
    description: str   # tooltip / help text
    default_on:  bool  # default state if user has never toggled it
    category:    str   # one of CATEGORIES


# ── Master kill switch (overrides all individual toggles) ────────────────────
MASTER_KEY     = "alerts_master_enabled"
MASTER_DEFAULT = True


# ══════════════════════════════════════════════════════════════════════════════
#  ALERT REGISTRY — add new alerts here
# ══════════════════════════════════════════════════════════════════════════════

ALERTS: dict[str, AlertDef] = {

    # ── Trading ──────────────────────────────────────────────────────────────
    "signal": AlertDef(
        key="alert_signal_enabled",
        label="Signal fired (BUY / SELL)",
        description="Confluence engine fired a BUY or SELL signal (score ≥ +6 or ≤ -6).",
        default_on=True,
        category="Trading",
    ),
    "order": AlertDef(
        key="alert_order_enabled",
        label="Order placed / failed",
        description="OrderManager placed an order (paper or live), or it failed.",
        default_on=True,
        category="Trading",
    ),
    "sl_hit": AlertDef(
        key="alert_sl_hit_enabled",
        label="Stop loss / target hit",
        description="Stop-loss or take-profit triggered on an open position.",
        default_on=True,
        category="Trading",
    ),

    # ── Risk ─────────────────────────────────────────────────────────────────
    "risk_breach": AlertDef(
        key="alert_risk_breach_enabled",
        label="Risk breach (loss limit / positions / Greeks)",
        description="Daily loss limit hit, max positions reached, or Greeks limit breached. CRITICAL — pauses trading.",
        default_on=True,
        category="Risk",
    ),

    # ── System ───────────────────────────────────────────────────────────────
    "crash": AlertDef(
        key="alert_crash_enabled",
        label="Service crash",
        description="process_guard detected a service crash and is restarting it.",
        default_on=True,
        category="System",
    ),
    "startup": AlertDef(
        key="alert_startup_enabled",
        label="System startup",
        description="process_guard started — services launched.",
        default_on=False,
        category="System",
    ),
    "token_expired": AlertDef(
        key="alert_token_expired_enabled",
        label="Kite token expired (mid-day)",
        description="Kite access token failed during market hours — orders will reject until renewed.",
        default_on=True,
        category="System",
    ),
    "token_alert": AlertDef(
        key="token_alert_enabled",   # legacy key — kept for backward compat
        label="Daily token expiry check (08:30–09:15 IST)",
        description="Telegram every 20 min if Kite token is missing/invalid before market open.",
        default_on=True,
        category="System",
    ),

    # ── Schedule ─────────────────────────────────────────────────────────────
    "pre_market_check": AlertDef(
        key="alert_pre_market_check_enabled",
        label="Pre-market check (09:10)",
        description="Scheduler verifies token is fresh 5 min before NSE opens.",
        default_on=True,
        category="Schedule",
    ),
    "market_open": AlertDef(
        key="alert_market_open_enabled",
        label="Market open ping (09:15)",
        description="Daily Telegram ping when NSE opens.",
        default_on=False,
        category="Schedule",
    ),
    "market_close": AlertDef(
        key="alert_market_close_enabled",
        label="Market close ping (15:30)",
        description="Daily Telegram ping when NSE closes (precedes EOD report).",
        default_on=False,
        category="Schedule",
    ),

    # ── Reports ──────────────────────────────────────────────────────────────
    "daily_report": AlertDef(
        key="alert_daily_report_enabled",
        label="Daily P&L report (15:45)",
        description="EOD summary — total P&L, trade count, win rate, best/worst trade per strategy.",
        default_on=True,
        category="Reports",
    ),

    # ── Manual (user-defined alerts) ─────────────────────────────────────────
    "price_alert": AlertDef(
        key="alert_price_alert_enabled",
        label="Manual price alerts",
        description="User-defined price alerts created in the Alerts page.",
        default_on=True,
        category="Manual",
    ),
    "pnl_alert": AlertDef(
        key="alert_pnl_alert_enabled",
        label="Manual P&L alerts",
        description="User-defined portfolio P&L alerts created in the Alerts page.",
        default_on=True,
        category="Manual",
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def is_enabled(alert_id: str) -> bool:
    """
    Returns True if alert should fire. Checks BOTH master switch AND per-alert toggle.
    Unknown alert_ids fail OPEN (return True) for backward compatibility.

    This is the gate every send_xxx() function in telegram.py + scheduler.py calls.
    """
    try:
        # Master kill switch overrides everything
        if not get_bool(MASTER_KEY, default=MASTER_DEFAULT):
            return False

        defn = ALERTS.get(alert_id)
        if defn is None:
            log.warning(f"Unknown alert_id '{alert_id}' — defaulting to enabled (fail-open)")
            return True

        return get_bool(defn.key, default=defn.default_on)

    except Exception:
        log.error(f"is_enabled() crashed for '{alert_id}' — defaulting to enabled", exc_info=True)
        return True   # fail-open: registry errors should not silently kill alerts


def set_enabled(alert_id: str, enabled: bool) -> bool:
    """Set per-alert toggle. Returns True on success."""
    try:
        defn = ALERTS.get(alert_id)
        if defn is None:
            log.warning(f"set_enabled: unknown alert_id '{alert_id}'")
            return False
        set_bool(defn.key, enabled)
        log.info(f"Alert '{alert_id}' {'ENABLED' if enabled else 'DISABLED'}")
        return True
    except Exception:
        log.error(f"set_enabled() failed for '{alert_id}'", exc_info=True)
        return False


def is_master_enabled() -> bool:
    """Master kill switch state."""
    try:
        return get_bool(MASTER_KEY, default=MASTER_DEFAULT)
    except Exception:
        log.error("is_master_enabled() failed — defaulting to True", exc_info=True)
        return True


def set_master_enabled(enabled: bool) -> None:
    """Master kill switch setter — instantly silences (or unsilences) ALL alerts."""
    try:
        set_bool(MASTER_KEY, enabled)
        log.info(f"🚨 MASTER ALERT SWITCH {'ON' if enabled else 'OFF'}")
    except Exception:
        log.error("set_master_enabled() failed", exc_info=True)


def list_by_category() -> dict[str, list[tuple[str, AlertDef, bool]]]:
    """
    Returns {category: [(alert_id, AlertDef, current_state), ...]} for UI rendering.
    Used by pages/6_System/2_System_Status.py.
    """
    result: dict[str, list[tuple[str, AlertDef, bool]]] = {c: [] for c in CATEGORIES}
    try:
        for alert_id, defn in ALERTS.items():
            current = get_bool(defn.key, default=defn.default_on)
            result.setdefault(defn.category, []).append((alert_id, defn, current))
    except Exception:
        log.error("list_by_category() failed", exc_info=True)
    return result


def status_summary() -> dict:
    """Quick summary for dashboard/health checks."""
    try:
        master = is_master_enabled()
        total  = len(ALERTS)
        on     = sum(1 for aid in ALERTS if is_enabled(aid))
        return {
            "master_enabled": master,
            "total_alerts":   total,
            "enabled_count":  on if master else 0,
            "disabled_count": total - on if master else total,
        }
    except Exception:
        log.error("status_summary() failed", exc_info=True)
        return {"master_enabled": True, "total_alerts": 0, "enabled_count": 0, "disabled_count": 0}


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        print("\n=== Alert Registry Status ===")
        s = status_summary()
        print(f"Master switch:  {'🟢 ON' if s['master_enabled'] else '🔴 OFF'}")
        print(f"Total alerts:   {s['total_alerts']}")
        print(f"Enabled:        {s['enabled_count']}")
        print(f"Disabled:       {s['disabled_count']}")
        print()
        for cat, items in list_by_category().items():
            if not items:
                continue
            print(f"── {cat} ──")
            for aid, defn, on in items:
                icon = "🟢" if on else "🔴"
                print(f"  {icon} {aid:20s} — {defn.label}")
            print()
    except Exception as e:
        print(f"❌ Registry test failed: {e}")
