"""
Database Layer — Supabase PostgreSQL (primary) + SQLite (local fallback)
=========================================================================
Primary:  Supabase PostgreSQL via DATABASE_URL
Fallback: Local dashboard.sqlite — kicks in automatically if Postgres is
          unreachable (network down, token issue, etc.)

All other files import from here — do NOT use psycopg2 or sqlite3 directly.

Usage:
    from db import execute, query, read_df, init_tables

    # Write
    execute("INSERT INTO engine_orders (...) VALUES (%s, %s)", (val1, val2))

    # Read rows
    rows = query("SELECT * FROM engine_orders WHERE symbol = %s", ("RELIANCE",))

    # Read as DataFrame
    df = read_df("SELECT * FROM strategy_trades WHERE DATE(timestamp) = %s", (today,))

Note: Use %s as placeholder (PostgreSQL style).
      Legacy ? placeholders are auto-converted for backwards compatibility.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from config import cfg
from logger import get_logger

log = get_logger("db")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "dashboard.sqlite"   # local fallback

# ── Detect PostgreSQL availability ────────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False
    log.warning("psycopg2 not installed — using SQLite only")

_USE_POSTGRES = _PSYCOPG2_AVAILABLE and bool(cfg.database_url)


# ── SQL placeholder normalisation ─────────────────────────────────────────────

def _to_pg(sql: str) -> str:
    """Convert SQLite ? → PostgreSQL %s."""
    return sql.replace("?", "%s")

def _to_sqlite(sql: str) -> str:
    """Convert PostgreSQL %s → SQLite ?."""
    return sql.replace("%s", "?")


# ── PostgreSQL connection ─────────────────────────────────────────────────────

@contextmanager
def _pg_conn():
    """Open a PostgreSQL connection with auto commit/rollback."""
    conn = psycopg2.connect(cfg.database_url, connect_timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── SQLite connection (fallback) ───────────────────────────────────────────────

@contextmanager
def _sqlite_conn():
    """Open a SQLite connection with auto commit/rollback."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
    """Run INSERT / UPDATE / DELETE. Tries PostgreSQL first, falls back to SQLite."""
    if _USE_POSTGRES:
        try:
            with _pg_conn() as conn:
                conn.cursor().execute(_to_pg(sql), params)
            return
        except Exception:
            log.error("PostgreSQL execute failed — falling back to SQLite", exc_info=True)

    # SQLite fallback
    try:
        with _sqlite_conn() as conn:
            conn.execute(_to_sqlite(sql), params)
    except Exception:
        log.error(f"SQLite execute failed\nSQL: {sql}\nParams: {params}", exc_info=True)
        raise


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run SELECT. Returns list of dicts. Tries PostgreSQL first, falls back to SQLite."""
    if _USE_POSTGRES:
        try:
            with _pg_conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(_to_pg(sql), params)
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            log.error("PostgreSQL query failed — falling back to SQLite", exc_info=True)

    # SQLite fallback
    try:
        with _sqlite_conn() as conn:
            cur = conn.execute(_to_sqlite(sql), params)
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        log.error(f"SQLite query failed\nSQL: {sql}\nParams: {params}", exc_info=True)
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
    """Run SELECT and return the first row as dict, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def count(table: str) -> int:
    """Quick row count for a table."""
    try:
        row = fetchone(f"SELECT COUNT(*) AS n FROM {table}")
        return int(row["n"]) if row else 0
    except Exception:
        return 0


def db_mode() -> str:
    """Returns 'postgresql' or 'sqlite' — useful for status pages."""
    return "postgresql" if _USE_POSTGRES else "sqlite"


# ── Table initialisation ──────────────────────────────────────────────────────

def init_tables() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    try:
        if _USE_POSTGRES:
            _init_postgres()
        else:
            _init_sqlite()
        log.info(f"✅ All tables ready ({db_mode()})")
    except Exception:
        log.error("init_tables() failed", exc_info=True)
        raise


def _init_postgres() -> None:
    with _pg_conn() as conn:
        cur = conn.cursor()

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


def _init_sqlite() -> None:
    with _sqlite_conn() as conn:

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
            print(f"✅ DB connected ({db_mode()}). engine_orders rows: {rows[0]['n']}")
        except Exception as e:
            print(f"❌ DB error: {e}")

    if args.init:
        init_tables()
        print(f"✅ Tables created ({db_mode()})")
