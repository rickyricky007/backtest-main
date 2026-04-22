"""Local SQLite persistence for Yahoo Finance history and strategy definitions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "dashboard.sqlite"

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_bars (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                bar_ts TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                adj_close REAL,
                volume REAL,
                PRIMARY KEY (symbol, interval, bar_ts)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_historical_symbol_interval
            ON historical_bars (symbol, interval)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                created_at TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_runs (strategy_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_group_members (
                group_id INTEGER NOT NULL,
                strategy_id INTEGER NOT NULL,
                PRIMARY KEY (group_id, strategy_id),
                FOREIGN KEY (group_id) REFERENCES strategy_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
            )
            """
        )


@contextmanager
def _connect() -> Any:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_float(row: pd.Series, *candidates: str) -> float | None:
    for c in candidates:
        if c in row.index:
            v = row[c]
            if pd.notna(v):
                return float(v)
    return None


def save_historical_bars(symbol: str, interval: str, df: pd.DataFrame) -> int:
    """Upsert OHLCV rows from a yfinance-style DataFrame (DatetimeIndex, capitalized OHLCV columns)."""
    if df is None or df.empty:
        return 0
    sym = symbol.strip().upper()
    inter = interval.strip()
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    rows: list[tuple] = []
    for ts, row in df.iterrows():
        ts = pd.Timestamp(ts)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        bar_ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        o = _row_float(row, "Open", "open")
        h = _row_float(row, "High", "high")
        l_ = _row_float(row, "Low", "low")
        c = _row_float(row, "Close", "close")
        if any(x is None or (isinstance(x, float) and x != x) for x in (o, h, l_, c)):
            continue
        adj_close = _row_float(row, "Adj Close", "AdjClose", "adj close")
        volume = _row_float(row, "Volume", "volume")
        rows.append((sym, inter, bar_ts, o, h, l_, c, adj_close, volume))

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO historical_bars (symbol, interval, bar_ts, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval, bar_ts) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                adj_close=excluded.adj_close,
                volume=excluded.volume
            """,
            rows,
        )
    return len(rows)


def list_historical_series() -> pd.DataFrame:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT symbol, interval, COUNT(*) AS bars,
                   MIN(bar_ts) AS first_bar, MAX(bar_ts) AS last_bar
            FROM historical_bars
            GROUP BY symbol, interval
            ORDER BY symbol, interval
            """
        )
        return pd.DataFrame(cur.fetchall(), columns=["symbol", "interval", "bars", "first_bar", "last_bar"])


def load_historical_bars(symbol: str, interval: str, *, limit: int | None = 5000) -> pd.DataFrame:
    sym = symbol.strip().upper()
    inter = interval.strip()
    q = """
        SELECT bar_ts, open, high, low, close, adj_close, volume
        FROM historical_bars
        WHERE symbol = ? AND interval = ?
        ORDER BY bar_ts ASC
    """
    params: list[Any] = [sym, inter]
    if limit is not None:
        q += " LIMIT ?"
        params.append(int(limit))
    with _connect() as conn:
        return pd.read_sql_query(q, conn, params=params, parse_dates=["bar_ts"])


def delete_historical_series(symbol: str, interval: str) -> int:
    sym = symbol.strip().upper()
    inter = interval.strip()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM historical_bars WHERE symbol = ? AND interval = ?",
            (sym, inter),
        )
        return cur.rowcount


def list_strategies() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            "SELECT id, name, description, config_json, created_at, updated_at FROM strategies ORDER BY name",
            conn,
        )


def create_strategy(name: str, description: str, config: dict[str, Any]) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Strategy name is required")
    now = _utc_now_iso()
    cfg = json.dumps(config, ensure_ascii=False)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO strategies (name, description, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, description or "", cfg, now, now),
        )
        return int(cur.lastrowid)


def update_strategy(strategy_id: int, name: str, description: str, config: dict[str, Any]) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Strategy name is required")
    now = _utc_now_iso()
    cfg = json.dumps(config, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE strategies
            SET name = ?, description = ?, config_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, description or "", cfg, now, int(strategy_id)),
        )


def delete_strategy(strategy_id: int) -> None:
    sid = int(strategy_id)
    with _connect() as conn:
        conn.execute("DELETE FROM backtest_runs WHERE strategy_id = ?", (sid,))
        conn.execute("DELETE FROM strategy_group_members WHERE strategy_id = ?", (sid,))
        conn.execute("DELETE FROM strategies WHERE id = ?", (sid,))


def get_strategy(strategy_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM strategies WHERE id = ?", (int(strategy_id),))
        row = cur.fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        try:
            d["config"] = json.loads(d["config_json"] or "{}")
        except json.JSONDecodeError:
            d["config"] = {}
        return d


def save_backtest_run(
    strategy_id: int,
    symbol: str,
    interval: str,
    *,
    summary: dict[str, Any],
    results_json: str,
) -> int:
    now = _utc_now_iso()
    sym = symbol.strip().upper()
    inter = interval.strip()
    sjson = json.dumps(summary, ensure_ascii=False)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO backtest_runs (strategy_id, symbol, interval, created_at, summary_json, results_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(strategy_id), sym, inter, now, sjson, results_json),
        )
        return int(cur.lastrowid)


def list_backtest_runs(*, limit: int = 100) -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT r.id, r.strategy_id,
                   COALESCE(s.name, '(deleted strategy)') AS strategy_name,
                   r.symbol, r.interval, r.created_at, r.summary_json
            FROM backtest_runs r
            LEFT JOIN strategies s ON s.id = r.strategy_id
            ORDER BY r.id DESC
            LIMIT ?
            """,
            conn,
            params=(int(limit),),
        )


def create_strategy_group(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Group name is required")
    now = _utc_now_iso()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO strategy_groups (name, created_at) VALUES (?, ?)",
            (name, now),
        )
        return int(cur.lastrowid)


def delete_strategy_group(group_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM strategy_groups WHERE id = ?", (int(group_id),))


def list_strategy_groups() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT g.id, g.name, g.created_at,
                   COUNT(m.strategy_id) AS n_strategies
            FROM strategy_groups g
            LEFT JOIN strategy_group_members m ON m.group_id = g.id
            GROUP BY g.id
            ORDER BY g.name
            """,
            conn,
        )


def add_strategy_to_group(group_id: int, strategy_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO strategy_group_members (group_id, strategy_id)
            VALUES (?, ?)
            """,
            (int(group_id), int(strategy_id)),
        )


def remove_strategy_from_group(group_id: int, strategy_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM strategy_group_members WHERE group_id = ? AND strategy_id = ?",
            (int(group_id), int(strategy_id)),
        )


def get_group_strategy_ids(group_id: int) -> list[int]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT strategy_id FROM strategy_group_members WHERE group_id = ? ORDER BY strategy_id",
            (int(group_id),),
        )
        return [int(r[0]) for r in cur.fetchall()]


def get_strategy_group(group_id: int) -> dict[str, Any] | None:
    gid = int(group_id)
    with _connect() as conn:
        cur = conn.execute("SELECT id, name, created_at FROM strategy_groups WHERE id = ?", (gid,))
        row = cur.fetchone()
        if not row:
            return None
        cur2 = conn.execute(
            "SELECT strategy_id FROM strategy_group_members WHERE group_id = ? ORDER BY strategy_id",
            (gid,),
        )
        ids = [int(r[0]) for r in cur2.fetchall()]
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "strategy_ids": ids,
        }


def list_group_members(group_id: int) -> pd.DataFrame:
    gid = int(group_id)
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT s.id AS strategy_id, s.name AS strategy_name
            FROM strategy_group_members m
            JOIN strategies s ON s.id = m.strategy_id
            WHERE m.group_id = ?
            ORDER BY s.name
            """,
            conn,
            params=(gid,),
        )


def get_backtest_run(run_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (int(run_id),))
        row = cur.fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        try:
            d["summary"] = json.loads(d["summary_json"] or "{}")
            d["results"] = json.loads(d["results_json"] or "{}")
        except json.JSONDecodeError:
            d["summary"] = {}
            d["results"] = {}
        return d


def db_path() -> Path:
    return DB_PATH


# ── Paper trading tables ───────────────────────────────────────────────────

def _init_paper_trading_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fo_portfolio (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            cash        REAL    NOT NULL DEFAULT 500000.0,
            positions   TEXT    NOT NULL DEFAULT '{}',
            updated_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fo_trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            action      TEXT    NOT NULL,
            underlying  TEXT    NOT NULL,
            symbol      TEXT    NOT NULL,
            expiry      TEXT    NOT NULL,
            strike      INTEGER NOT NULL,
            opt_type    TEXT    NOT NULL,
            lots        INTEGER NOT NULL,
            lot_size    INTEGER NOT NULL,
            qty         INTEGER NOT NULL,
            price       REAL    NOT NULL,
            premium     REAL    NOT NULL,
            trade_type  TEXT    NOT NULL DEFAULT 'paper',
            traded_at   TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fo_trades_underlying ON fo_trades (underlying, traded_at)"
    )


def load_fo_portfolio(starting_capital: float = 500_000.0) -> dict:
    with _connect() as conn:
        _init_paper_trading_tables(conn)
        row = conn.execute(
            "SELECT cash, positions FROM fo_portfolio WHERE id = 1"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO fo_portfolio (id, cash, positions, updated_at) VALUES (1, ?, '{}', ?)",
                (starting_capital, _utc_now_iso()),
            )
            return {"cash": starting_capital, "positions": {}}
        return {"cash": row["cash"], "positions": json.loads(row["positions"] or "{}")}


def save_fo_portfolio(portfolio: dict) -> None:
    with _connect() as conn:
        _init_paper_trading_tables(conn)
        conn.execute(
            """
            INSERT INTO fo_portfolio (id, cash, positions, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                cash       = excluded.cash,
                positions  = excluded.positions,
                updated_at = excluded.updated_at
            """,
            (
                float(portfolio["cash"]),
                json.dumps(portfolio.get("positions") or {}, ensure_ascii=False),
                _utc_now_iso(),
            ),
        )


def reset_fo_portfolio(starting_capital: float = 500_000.0) -> None:
    save_fo_portfolio({"cash": starting_capital, "positions": {}})


def append_fo_trade(trade: dict) -> int:
    with _connect() as conn:
        _init_paper_trading_tables(conn)
        cur = conn.execute(
            """
            INSERT INTO fo_trades
                (action, underlying, symbol, expiry, strike, opt_type,
                 lots, lot_size, qty, price, premium, trade_type, traded_at)
            VALUES
                (:action, :underlying, :symbol, :expiry, :strike, :opt_type,
                 :lots, :lot_size, :qty, :price, :premium,
                 :trade_type, :traded_at)
            """,
            {
                "action":     trade["action"],
                "underlying": trade["underlying"],
                "symbol":     trade["symbol"],
                "expiry":     trade["expiry"],
                "strike":     int(trade["strike"]),
                "opt_type":   trade["opt_type"],
                "lots":       int(trade["lots"]),
                "lot_size":   int(trade["lot_size"]),
                "qty":        int(trade["qty"]),
                "price":      float(trade["price"]),
                "premium":    float(trade["premium"]),
                "trade_type": trade.get("trade_type", "paper"),
                "traded_at":  trade.get("traded_at") or _utc_now_iso(),
            },
        )
        return cur.lastrowid


def load_fo_trades(limit: int = 500) -> list[dict]:
    with _connect() as conn:
        _init_paper_trading_tables(conn)
        rows = conn.execute(
            "SELECT * FROM fo_trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def clear_fo_trades() -> None:
    with _connect() as conn:
        _init_paper_trading_tables(conn)
        conn.execute("DELETE FROM fo_trades")


# ── Alerts & Settings tables ───────────────────────────────────────────────

def _init_alert_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type   TEXT    NOT NULL,
            display_name TEXT    NOT NULL,
            symbol       TEXT,
            exchange     TEXT,
            condition    TEXT    NOT NULL,
            target_value REAL    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'ACTIVE',
            created_at   TEXT    NOT NULL,
            triggered_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def create_alert(
    alert_type: str,
    display_name: str,
    symbol: str | None,
    exchange: str | None,
    condition: str,
    target_value: float,
) -> int:
    now = _utc_now_iso()
    with _connect() as conn:
        _init_alert_tables(conn)
        cur = conn.execute(
            """
            INSERT INTO alerts
                (alert_type, display_name, symbol, exchange, condition, target_value, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (alert_type, display_name, symbol, exchange, condition, float(target_value), now),
        )
        return int(cur.lastrowid)


def load_active_alerts() -> list[dict]:
    with _connect() as conn:
        _init_alert_tables(conn)
        rows = conn.execute(
            "SELECT * FROM alerts WHERE status = 'ACTIVE' ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def load_all_alerts(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        _init_alert_tables(conn)
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_alert_triggered(alert_id: int) -> None:
    now = _utc_now_iso()
    with _connect() as conn:
        _init_alert_tables(conn)
        conn.execute(
            "UPDATE alerts SET status = 'TRIGGERED', triggered_at = ? WHERE id = ?",
            (now, int(alert_id)),
        )


def delete_alert(alert_id: int) -> None:
    with _connect() as conn:
        _init_alert_tables(conn)
        conn.execute("DELETE FROM alerts WHERE id = ?", (int(alert_id),))


def clear_triggered_alerts() -> None:
    with _connect() as conn:
        _init_alert_tables(conn)
        conn.execute("DELETE FROM alerts WHERE status = 'TRIGGERED'")


def get_setting(key: str) -> str | None:
    with _connect() as conn:
        _init_alert_tables(conn)
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        _init_alert_tables(conn)
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
