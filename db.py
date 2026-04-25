"""
Database Layer — Supabase (PostgreSQL)
======================================
Central database module. All other files import from here.
Replaces direct sqlite3 usage across the codebase.

Usage:
    from db import execute, query, read_df, init_tables

    # Write
    execute("INSERT INTO engine_orders (...) VALUES (%s, %s)", (val1, val2))

    # Read rows
    rows = query("SELECT * FROM engine_orders WHERE symbol = %s", ("RELIANCE",))

    # Read as DataFrame
    df = read_df("SELECT * FROM strategy_trades WHERE DATE(timestamp) = %s", (today,))
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ── Connection string ─────────────────────────────────────────────────────────
_DATABASE_URL = os.getenv("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL not set in .env\n"
        "Add: DATABASE_URL=postgresql://postgres.xxx:password@host:6543/postgres"
    )


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def _conn():
    """Context manager — opens a connection, commits on success, rolls back on error."""
    conn = psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
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
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT and return list of dicts."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def read_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a SELECT and return a pandas DataFrame."""
    rows = query(sql, params)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    """Run a SELECT and return the first row as dict, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def count(table: str) -> int:
    """Quick row count for a table."""
    row = fetchone(f"SELECT COUNT(*) AS n FROM {table}")
    return row["n"] if row else 0


# ── Table initialisation ──────────────────────────────────────────────────────

def init_tables() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with _conn() as conn:
        with conn.cursor() as cur:

            # ── engine_orders ──────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS engine_orders (
                    id              SERIAL PRIMARY KEY,
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
                    mode            TEXT    NOT NULL,
                    order_id        TEXT    DEFAULT '',
                    status          TEXT    DEFAULT 'OPEN',
                    fill_price      REAL    DEFAULT 0,
                    signal_price    REAL    DEFAULT 0,
                    slippage_amt    REAL    DEFAULT 0,
                    slippage_pct    REAL    DEFAULT 0,
                    notes           TEXT    DEFAULT ''
                )
            """)

            # ── strategy_trades ────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS strategy_trades (
                    id          SERIAL PRIMARY KEY,
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

            # ── sl_positions ───────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sl_positions (
                    id              SERIAL PRIMARY KEY,
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

            # ── trade_journal ──────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id              SERIAL PRIMARY KEY,
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

    print("[DB] ✅ All tables ready in Supabase")


# ── Migrate from SQLite (run once) ────────────────────────────────────────────

def migrate_from_sqlite(sqlite_path: str | Path | None = None) -> None:
    """
    One-time migration: copy all rows from local SQLite → Supabase.
    Run once from terminal:  python db.py --migrate
    """
    import sqlite3 as _sqlite3

    if sqlite_path is None:
        sqlite_path = Path(__file__).parent / "dashboard.sqlite"

    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        print(f"[Migrate] SQLite file not found: {sqlite_path}")
        return

    src = _sqlite3.connect(str(sqlite_path))
    src.row_factory = _sqlite3.Row

    tables = ["engine_orders", "strategy_trades", "sl_positions", "trade_journal"]

    for table in tables:
        try:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
        except Exception:
            print(f"[Migrate] Table {table} not found in SQLite — skipping")
            continue

        if not rows:
            print(f"[Migrate] {table}: empty — skipping")
            continue

        cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 0").description
                if d[0] != "id"]  # skip id — PostgreSQL SERIAL generates its own

        placeholders = ", ".join(["%s"] * len(cols))
        col_names    = ", ".join(cols)
        sql          = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        inserted = 0
        with _conn() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    values = tuple(row[c] for c in cols)
                    try:
                        cur.execute(sql, values)
                        inserted += 1
                    except Exception as e:
                        print(f"[Migrate] Row error in {table}: {e}")

        print(f"[Migrate] {table}: {inserted}/{len(rows)} rows migrated ✅")

    src.close()
    print("[Migrate] Done!")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init",    action="store_true", help="Create tables in Supabase")
    parser.add_argument("--migrate", action="store_true", help="Migrate SQLite → Supabase")
    parser.add_argument("--test",    action="store_true", help="Test connection")
    args = parser.parse_args()

    if args.test:
        try:
            rows = query("SELECT NOW() AS now")
            print(f"[DB] ✅ Connected! Server time: {rows[0]['now']}")
        except Exception as e:
            print(f"[DB] ❌ Connection failed: {e}")

    if args.init:
        init_tables()

    if args.migrate:
        init_tables()
        migrate_from_sqlite()
