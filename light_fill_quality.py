"""
Light L1 — fill quality rows from `engine_orders` (Phase 2 tracking).
Reads typed columns when present; falls back to JSON in `notes` for older rows.
"""

from __future__ import annotations

import json
from typing import Any

from db import query

LIGHT_STRATEGY_NAME = "Light_NIFTY_RSI"


def light_l1_last_order() -> dict[str, Any] | None:
    """Latest `engine_orders` row for Light L1 (for mission control)."""
    rows = query(
        """
        SELECT id, timestamp, symbol, action, mode, status, order_id,
               price, signal_price, fill_price
        FROM engine_orders
        WHERE strategy = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (LIGHT_STRATEGY_NAME,),
    )
    return dict(rows[0]) if rows else None


def _notes_dict(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def light_l1_fill_rows(limit: int = 200) -> list[dict[str, Any]]:
    """Recent Light L1 orders with unified signal/fill/slip/sim/IV fields."""
    rows = query(
        """
        SELECT id, timestamp, symbol, action, exchange, mode, price,
               signal_price, fill_price, slippage_amt, slippage_pct, notes
        FROM engine_orders
        WHERE strategy = %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (LIGHT_STRATEGY_NAME, limit),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        notes = _notes_dict(r.get("notes"))
        sig = float(r.get("signal_price") or 0.0)
        if not sig:
            sig = float(notes.get("signal_price") or 0.0)
        fill = float(r.get("fill_price") or 0.0)
        if not fill:
            fill = float(notes.get("fill_price") or 0.0)
        if not fill:
            fill = float(r.get("price") or 0.0)
        slip_amt = float(r.get("slippage_amt") or 0.0)
        if not slip_amt and sig and fill:
            slip_amt = abs(fill - sig)
        if not slip_amt:
            slip_amt = float(notes.get("slippage_amt") or 0.0)
        slip_pct = float(r.get("slippage_pct") or 0.0)
        if not slip_pct and sig > 0:
            slip_pct = abs(fill - sig) / sig * 100.0
        if not slip_pct:
            slip_pct = float(notes.get("slippage_pct") or 0.0)

        mid_sim = notes.get("mid_premium_assumption")
        iv = notes.get("iv_quote")
        if iv is None:
            iv = notes.get("iv")

        out.append(
            {
                "id": r["id"],
                "timestamp": r.get("timestamp"),
                "symbol": r.get("symbol"),
                "action": r.get("action"),
                "exchange": r.get("exchange"),
                "mode": r.get("mode"),
                "signal_inr": round(sig, 4) if sig else None,
                "fill_inr": round(fill, 4) if fill else None,
                "slip_inr": round(slip_amt, 4) if slip_amt else None,
                "slip_pct": round(slip_pct, 4) if slip_pct else None,
                "mid_premium_sim_inr": mid_sim,
                "iv_quote": iv,
            }
        )
    return out
