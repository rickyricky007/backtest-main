"""
app_settings.py — Persistent key/value settings (toggles, flags, prefs)
======================================================================
Stored in `app_settings` table. Survives restarts, shared across pages.

Usage:
    from app_settings import get_setting, set_setting, get_bool, set_bool

    if get_bool("token_alert_enabled", default=True):
        ...
    set_bool("token_alert_enabled", False)
"""

from __future__ import annotations

from db import execute, fetchone, _USE_POSTGRES
from logger import get_logger

log = get_logger("app_settings")


def _ensure_table() -> None:
    """Create app_settings table if missing (idempotent)."""
    try:
        if _USE_POSTGRES:
            execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
            """)
        else:
            execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
            """)
    except Exception:
        log.error("Failed to ensure app_settings table", exc_info=True)


_ensure_table()


def get_setting(key: str, default: str = "") -> str:
    """Read a setting. Returns default if missing."""
    try:
        row = fetchone("SELECT value FROM app_settings WHERE key = %s", (key,))
        return row["value"] if row else default
    except Exception:
        log.error(f"get_setting failed for key={key}", exc_info=True)
        return default


def set_setting(key: str, value: str) -> None:
    """Upsert a setting."""
    try:
        if _USE_POSTGRES:
            execute(
                "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )
        else:
            execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
    except Exception:
        log.error(f"set_setting failed for key={key}", exc_info=True)


def get_bool(key: str, default: bool = False) -> bool:
    """Read a boolean setting."""
    try:
        v = get_setting(key, "1" if default else "0")
        return v.strip() in ("1", "true", "True", "yes", "on")
    except Exception:
        log.error(f"get_bool failed for key={key}", exc_info=True)
        return default


def set_bool(key: str, value: bool) -> None:
    """Write a boolean setting."""
    try:
        set_setting(key, "1" if value else "0")
    except Exception:
        log.error(f"set_bool failed for key={key}", exc_info=True)
