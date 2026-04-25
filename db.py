"""
Database Layer — SQLite
========================
Central database module for the algo trading system.
All other files import from here — do NOT use sqlite3 directly.

Usage:
    from db import execute, query, read_df, init_tables

    # Write
    execute("INSERT INTO engine_orders (...) VALUES (?, ?)", (val1, val2))

    # Read rows
    rows = query("SELECT * FROM engine_orders WHERE symbol = ?", ("RELIANCE",))

    # Read as DataFrame
    df = read_df("SELECT * FROM strategy_trades WHERE DATE(timestamp) = ?", (today,))

Note: Use ? as placeholder (SQLite style), NOT %s.
      Legacy %s placeholders are auto-converted for backwards compatibility.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from logger import get_logger

log = get_logger("db")

# ── DB path ───────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "dashboard.sqlite"


def _fix_sql(sql: str) -> str:
    """Convert %s → ? for backwards compatibility with old PostgreSQL-style queries."""
    return sql.replace("%s", "?")


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def _conn():
    """Open a SQLite connection, commit on success, rollback on error."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # allows concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────

def execute(sql: str, params: tuple = ()) -> None:
    """Run an INSERT / UPDATE / DELETE statement."""
    try:
        with _conn() as conn:
            conn.execute(_fix_sql(sql), params)
    except Exception:
        log.error(f"DB execute failed\nSQL: {sql}\nParams: {params}", exc_info=True)
        raise


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return list of dicts."""
    try:
        with _conn() as conn:
            cur = conn.execute(_fix_sql(sql), params)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        log.error(f"DB query failed\nSQL: {sql}\nParams: {params}", exc_info=True)
        return []


def read_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a SELECT and return a pandas DataFrame."""
    try:
        rows = query(sql, params)
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception:
        log.error("read_df failed", exc_info=True)
        return pd.DataFrame()


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    """Run a SELECT and return the first row as dict, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def count(table: str) -> int:
    """Quick row count for a table."""
    try:
        row = fetchone(f"SELECT COUNT(*) AS n FROM {table}")
        return row["n"] if row else 0
    except Exception:
        return 0


# ── Table initialisation ──────────────────────────────────────────────────────

def init_tables() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    try:
        with _conn() as conn:

            # ── engine_orders ──────────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS engine_orders (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    strategy        TEXT    NOT NULL DEFAULT '',
                    symbol          TEXT    NOT NULL,
                    exchange        TEXT    NOT NULL DEFAULT 'NSE',
                    action          TEXT    NOT NULL,
                    order_type      TEXT    NOT NULL DEFAULT 'MARKET',
                    variety         TEXT    NOT NULL DEFAULT 'REGULAR',
                    product         TEXT    NOT NULL DEFAULT 'MIS',
                    quantity        INTEGER NOT NULL,
                    price           REAL    DEFAULT 0,
                    trigger_price   REAL    DEFAULT 0,
                    sq_off          REAL    DEFAULT 0,
                    stoploss        REAL    DEFAULT 0,
                    trailing_sl     REAL    DEFAULT 0,
                    mode            TEXT    NOT NULL DEFAULT 'PAPER',
                    order_id        TEXT    DEFAULT '',
                    status          TEXT    DEFAULT 'OPEN',
                    fill_price      REAL    DEFAULT 0,
                    signal_price    REAL    DEFAULT 0,
                    slippage_amt    REAL    DEFAULT 0,
                    slippage_pct    REAL    DEFAULT 0,
                    notes           TEXT    DEFAULT ''
                )
            """)

            # ── strategy_trades ────────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    strategy    TEXT    NOT NULL,
                    symbol      TEXT    NOT NULL,
                    action      TEXT    NOT NULL,
                    price       REAL,
                    quantity    INTEGER DEFAULT 1,
                    pnl         REAL    DEFAULT 0,
                    mode        TEXT    DEFAULT 'PAPER',
                    notes       TEXT    DEFAULT ''
                )
            """)

            # ── sl_positions ───────────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sl_positions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT    NOT NULL,
                    exchange        TEXT    NOT NULL DEFAULT 'NSE',
                    action          TEXT    NOT NULL,
                    qty             INTEGER NOT NULL,
                    entry_price     REAL    NOT NULL,
                    sl_price        REAL    NOT NULL,
                    target_price    REAL,
                    trailing_sl     REAL    DEFAULT 0,
                    peak_price      REAL,
                    entry_time      TEXT,
                    strategy        TEXT    DEFAULT '',
                    status          TEXT    DEFAULT 'OPEN'
                )
            """)

            # ── trade_journal ──────────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    date            TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    setup           TEXT,
                    direction       TEXT,
                    entry_price     REAL,
                    exit_price      REAL,
                    quantity        INTEGER DEFAULT 1,
                    pnl             REAL    DEFAULT 0,
                    emotion         TEXT,
                    notes           TEXT,
                    tags            TEXT,
                    created_at      TEXT    DEFAULT ''
                )
            """)

        log.info("✅ All tables ready (SQLite)")

    except Exception:
        log.error("init_tables() failed", exc_info=True)
        raise


# ── Auto-init on import ───────────────────────────────────────────────────────
try:
    init_tables()
except Exception:
    log.error("Failed to auto-init tables on import", exc_info=True)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Create tables")
    parser.add_argument("--test", action="store_true", help="Test connection")
    args = parser.parse_args()

    if args.test:
        try:
            rows = query("SELECT COUNT(*) AS n FROM engine_orders")
            print(f"✅ DB connected. engine_orders rows: {rows[0]['n']}")
        except Exception as e:
            print(f"❌ DB error: {e}")

    if args.init:
        init_tables()
        print("✅ Tables created")
