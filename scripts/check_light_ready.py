#!/usr/bin/env python3
"""
Pre-flight checks: DB, Kite token, Light L1 config.
Run from repo root:  python scripts/check_light_ready.py
Or:                  make status   (see Makefile)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ok = True
    warn = False

    print("Light L1 / stack readiness")
    print("—" * 40)

    try:
        from db import db_mode, query

        rows = query("SELECT COUNT(*) AS n FROM engine_orders", ())
        n = int(rows[0]["n"]) if rows else 0
        print(f"[OK] Database ({db_mode()}): engine_orders rows={n}")
    except Exception as e:
        print(f"[FAIL] Database: {e}")
        ok = False

    tok = ROOT / ".kite_access_token"
    if tok.is_file() and tok.read_text(encoding="utf-8").strip():
        print("[OK] Kite token file (.kite_access_token)")
    else:
        print("[WARN] Missing or empty .kite_access_token — connect Kite before trading APIs")
        warn = True

    breeze = ROOT / ".breeze_session"
    if breeze.is_file():
        print("[OK] Breeze session file present (optional data source)")
    else:
        print("[INFO] No .breeze_session — data falls back to Kite/yfinance where applicable")

    try:
        from light_strategy_config import is_light_l1_enabled, load_config

        cfg = load_config(force=True)
        print(
            f"[OK] light_l1_config: mode={cfg.mode}, "
            f"max_trades/day={cfg.max_trades_per_day}, lots={cfg.lot_size}"
        )
        print(f"[INFO] Light L1 engine toggle (app_settings): {'ON' if is_light_l1_enabled() else 'OFF'}")
    except Exception as e:
        print(f"[FAIL] light_l1_config: {e}")
        ok = False

    print("—" * 40)
    if not ok:
        print("Result: FAIL — fix errors above")
        return 1
    if warn:
        print("Result: OK with warnings")
        return 0
    print("Result: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
