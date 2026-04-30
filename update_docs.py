"""
Auto-Doc Updater — Keeps CLAUDE.md always current
===================================================
Scans the entire codebase and regenerates CLAUDE.md automatically.

Run after every session:
    python update_docs.py

Or add to your end-of-day routine:
    python update_docs.py && git add CLAUDE.md && git commit -m "docs: auto-update"
"""

from __future__ import annotations

import ast
import subprocess
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Helpers ───────────────────────────────────────────────────────────────────

def _git_log(n: int = 5) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "log", f"-{n}", "--oneline"], cwd=BASE_DIR, text=True
        )
        return out.strip().splitlines()
    except Exception:
        return []


def _docstring(path: Path) -> str:
    """Extract first line of module docstring."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
        doc  = ast.get_docstring(tree)
        if doc:
            return doc.splitlines()[0].strip()
    except Exception:
        pass
    return ""


def _count_lines(path: Path) -> int:
    try:
        return len(path.read_text(errors="replace").splitlines())
    except Exception:
        return 0


def _file_table(files: list[Path], base: Path) -> str:
    rows = ["| File | Purpose | Lines |", "|------|---------|-------|"]
    for f in sorted(files):
        rel   = f.relative_to(base)
        doc   = _docstring(f) or "—"
        lines = _count_lines(f)
        rows.append(f"| `{rel}` | {doc} | {lines} |")
    return "\n".join(rows)


def _page_table(pages: list[Path]) -> str:
    rows = ["| Page | Route | Description |", "|------|-------|-------------|"]
    for p in sorted(pages):
        name  = p.stem
        route = "/" + name.split("_", 1)[-1].replace("_", " ") if "_" in name else name
        doc   = _docstring(p) or "—"
        rows.append(f"| `{name}` | `{route}` | {doc} |")
    return "\n".join(rows)


def _db_tables() -> str:
    import sqlite3
    db = BASE_DIR / "dashboard.sqlite"
    if not db.exists():
        return "_database.sqlite not found — run the app first_"
    try:
        conn   = sqlite3.connect(str(db))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        conn.close()
        rows   = ["| Table | Description |", "|-------|-------------|"]
        desc_map = {
            "engine_orders":   "All orders (paper + live) with fill info",
            "strategy_trades": "Strategy signal log with P&L",
            "sl_positions":    "Active stop-loss positions",
            "trade_journal":   "Manual trade diary entries",
        }
        for (t,) in tables:
            rows.append(f"| `{t}` | {desc_map.get(t, '—')} |")
        return "\n".join(rows)
    except Exception:
        return "_Could not read DB tables_"


# ── Main builder ──────────────────────────────────────────────────────────────

def _section_pages() -> dict[str, list[Path]]:
    """Scan pages/ subdirectories and return {section_name: [page_files]}."""
    sections: dict[str, list[Path]] = {}
    pages_dir = BASE_DIR / "pages"
    # Subdirectory sections (new organized structure)
    for folder in sorted(pages_dir.iterdir()):
        if folder.is_dir() and not folder.name.startswith("_") and not folder.name.startswith("."):
            files = sorted([f for f in folder.glob("*.py") if not f.name.startswith("__")])
            if files:
                # Strip leading number prefix for display e.g. "1_Account" → "Account"
                label = folder.name.split("_", 1)[-1] if "_" in folder.name else folder.name
                sections[label] = files
    # Flat pages fallback (if no subdirs found)
    if not sections:
        flat = sorted([f for f in pages_dir.glob("*.py") if not f.name.startswith("__")])
        if flat:
            sections["Pages"] = flat
    return sections


def _page_section_table(sections: dict[str, list[Path]]) -> str:
    rows = ["| Section | Page | Description |", "|---------|------|-------------|"]
    for section, files in sections.items():
        for f in files:
            name = f.stem.split("_", 1)[-1].replace("_", " ") if "_" in f.stem else f.stem
            doc  = _docstring(f) or "—"
            rows.append(f"| **{section}** | `{name}` | {doc} |")
    return "\n".join(rows)


def build_claude_md() -> str:
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = _section_pages()
    pages    = [f for files in sections.values() for f in files]  # flat list for count
    core_files = [
        BASE_DIR / f for f in [
            "app.py", "home.py", "kite_data.py", "config.py", "auth_streamlit.py",
            "generate_token.py", "alert_engine.py", "logger.py",
        ] if (BASE_DIR / f).exists()
    ]
    live_files = [
        BASE_DIR / f for f in [
            "ticker_service.py", "market_data.py",
        ] if (BASE_DIR / f).exists()
    ]
    strategy_files = sorted((BASE_DIR / "strategies").glob("*.py")) if (BASE_DIR / "strategies").exists() else []
    strategy_files = [f for f in strategy_files if not f.name.startswith("__")]

    engine_files = [
        BASE_DIR / f for f in [
            "strategy_engine.py", "signal_engine.py", "indicators.py",
            "fo_symbols.py", "regime_filter.py",
        ] if (BASE_DIR / f).exists()
    ]
    exec_files = [
        BASE_DIR / f for f in [
            "order_manager.py", "stop_loss_manager.py",
            "risk_manager.py", "position_sizer.py",
        ] if (BASE_DIR / f).exists()
    ]
    infra_files = [
        BASE_DIR / f for f in [
            "process_guard.py", "scheduler.py",
            "auto_renew_token.py", "db.py",
        ] if (BASE_DIR / f).exists()
    ]
    backtest_files = [
        BASE_DIR / f for f in [
            "backtest_engine.py", "backtest_runner.py",
        ] if (BASE_DIR / f).exists()
    ]

    recent_commits = "\n".join(f"- {c}" for c in _git_log(5)) or "_No git history_"

    doc = f"""# Algo Trading System — Project Map
> Auto-generated on **{now}** — updates automatically every time the app starts.

---

## What this project is
A production-grade algorithmic trading system built on Zerodha Kite API + Streamlit dashboard.
**Owner:** Ricky | **Broker:** Zerodha | **Exchange:** NSE / NFO (F&O)

---

## How to start every session
```bash
cd ~/algo_trading/"ricky 1"
source venv/bin/activate

# Step 1 — get login URL, open in browser, copy request_token from redirect URL
python -c "from kiteconnect import KiteConnect; import os; from dotenv import load_dotenv; load_dotenv(); k = KiteConnect(api_key=os.getenv('API_KEY')); print(k.login_url())"

# Step 2 — paste request_token here (do this once every morning)
python generate_token.py <request_token>

# Step 3 — start everything (dashboard + ticker + strategy engine)
python process_guard.py
```
Dashboard opens at **http://localhost:8501**
Navigation: Home → Account → Market → Signals → Trading → Analytics → System

---

## Environment (.env)
| Key | Description |
|-----|-------------|
| `API_KEY` | Kite API key (also `KITE_API_KEY`) |
| `API_SECRET` | Kite API secret (also `KITE_API_SECRET`) |
| `TELEGRAM_TOKEN` | Telegram bot token (also `TELEGRAM_BOT_TOKEN`) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `ANTHROPIC_API_KEY` | Claude API key (for chatbot page) |

**All keys unified via `config.py` — always import `cfg` from there.**

---

## Dashboard Pages ({len(pages)} pages across {len(sections)} sections)

{_page_section_table(sections)}

---

## File Map

### Core
{_file_table(core_files, BASE_DIR)}

### Live Data
{_file_table(live_files, BASE_DIR)}

### Signal & Intelligence Layer
{_file_table(engine_files, BASE_DIR)}

### Strategy Layer
{_file_table(strategy_files, BASE_DIR) if strategy_files else "_See strategies/ folder_"}

### Execution Layer
{_file_table(exec_files, BASE_DIR)}

### Backtesting
{_file_table(backtest_files, BASE_DIR)}

### Infrastructure
{_file_table(infra_files, BASE_DIR)}

---

## Database (`dashboard.sqlite`)
{_db_tables()}

---

## Signal Scoring System
- **10 indicators:** RSI, MACD, Bollinger Bands, Supertrend, EMA Crossover, VWAP, Volume Spike, ADX, Stochastic, OI Change
- **Score range:** -15 to +15
- **BUY threshold:** ≥ +6 | **SELL threshold:** ≤ -6
- **Universe:** 6 F&O indices + ~180 F&O stocks (`fo_symbols.py`)

---

## Adding a new strategy
1. Create `strategies/my_strategy.py` inheriting `BaseStrategy`
2. Implement `name`, `description`, `on_tick()` → return `Signal` or `None`
3. Add to `strategies/__init__.py`
4. Add to `ACTIVE_STRATEGIES` in `strategy_engine.py`
5. Add to `STRATEGY_MAP` in `pages/16_Backtest.py`

## Adding a new indicator
1. Add function `check_xxx()` to `indicators.py` returning +weight / -weight / 0
2. Call it inside `score_symbol()` and add to `_add()` calls
3. Update `MAX_SCORE` at top of file

---

## Key architectural decisions
- **Navigation:** `app.py` uses `st.navigation()` with 7 sections — Home, Account, Market, Signals, Trading, Analytics, System
- **Home page:** `home.py` — overview with live indices, holdings, positions preview
- **Terminal-only auth:** run `python generate_token.py <request_token>` once every morning
- **WebSocket ticks:** `ticker_service.py` writes `ticker_data.json` every tick
- **Confluence scoring:** 10-indicator weighted system — trade only on agreement
- **PAPER / LIVE modes:** one toggle in Signal Scanner or Strategy Hub — no code changes needed
- **Central logger:** ALL files use `from logger import get_logger` — no bare print()
- **Central DB:** ALL files use `from db import execute, query, read_df`
- **Single symbol registry:** always import from `fo_symbols.py` — never hardcode symbols
- **Error handling:** ALL files use try/except with logger — never bare except:
- **Auto docs:** CLAUDE.md regenerates automatically on every app startup
- **AI responses:** key things only — no fluff, no unnecessary explanation
- **Better idea rule:** if a safer/better approach exists, say it first before building — money is at risk
- **Response style:** direct, concise, production-safe
- **Change log rule:** every product update or code change must be noted in CLAUDE.md

---

## Change Log
> One-line notes only — what changed, why, which file. No code.

- 2026-04-26 | Built `signal_engine.py` — 10-indicator confluence scanner for all F&O symbols
- 2026-04-26 | Built `indicators.py` — weighted scoring system (±15, BUY ≥+6, SELL ≤-6)
- 2026-04-26 | Built `fo_symbols.py` — single source of truth for all F&O symbols (6 indices + 180 stocks)
- 2026-04-26 | Built `pages/17_Signal_Scanner.py` — live BUY/SELL/WAIT dashboard with paper trade button
- 2026-04-26 | Built `market_intelligence.py` — OI analysis, expiry alerts, manipulation detection, max pain
- 2026-04-26 | Built `pages/18_Charts.py` — Plotly interactive charts, all F&O, multi-timeframe, signal markers
- 2026-04-26 | Upgraded `pages/11_Options_Chain.py` — all 180+ F&O stocks + indices, OI chart, strategy launcher
- 2026-04-26 | Upgraded `pages/6_Chatbot.py` — full product knowledge, global market hours, DB context
- 2026-04-26 | Fixed `db.py` — switched from broken PostgreSQL to SQLite with same API
- 2026-04-26 | Built `logger.py` — central rotating logger, all files now use get_logger()
- 2026-04-26 | Built `update_docs.py` — auto-regenerates CLAUDE.md on every app startup
- 2026-04-26 | Reorganised sidebar — 7 sections using st.navigation() (Home/Account/Market/Signals/Trading/Analytics/System)
- 2026-04-26 | Created `home.py` — overview page split from app.py for clean navigation shell
- 2026-04-26 | Built `telegram.py` — unified Telegram alert module wired to all key services
- 2026-04-26 | Built `db_backup.py` — daily SQLite backup, keeps last 7, triggered automatically at 3:30pm
- 2026-04-26 | Built `token_monitor.py` — detects expired Kite token every 5 min, Telegram alert with fix steps
- 2026-04-26 | Built `daily_report.py` — 3:30pm P&L summary to Telegram + triggers DB backup
- 2026-04-26 | Updated `process_guard.py` — added token_monitor and daily_report as managed services
- 2026-04-26 | Built `tests/test_indicators.py` — 15 unit tests covering RSI, EMA, volume spike, score_symbol
- 2026-04-26 | Built `tests/test_risk_manager.py` — 14 unit tests covering all risk gates (loss limit, positions, Greeks, hours)
- 2026-04-27 | VPS deployed — AWS t3.micro, Mumbai (ap-south-1), IP 65.2.22.171, Ubuntu 22.04 LTS
- 2026-04-27 | Built `deploy/setup_vps.sh` — one-command full setup: Python 3.11, Nginx, 5 systemd services
- 2026-04-27 | Built `deploy/restart.sh` / `status.sh` / `update.sh` — VPS management scripts
- 2026-04-27 | Added `algotrading-ticker` systemd service — runs ticker_service.py 24/7 for live WebSocket prices
- 2026-04-27 | Fixed 15-min delay issue — ticker_service.py must run as service (was missing from VPS services)
- 2026-04-27 | Added yfinance install to update.sh — US futures/gold/crude data for global market widget
- 2026-04-27 | SEBI rule: static IP mandatory from Apr 1 2026 for all broker APIs — VPS IP 65.2.22.171 used
- 2026-04-30 | ✅ VPS IP 65.2.22.171 registered with Zerodha Kite — live orders enabled
- 2026-04-27 | Breeze app registered — API key: 295593q0yl0367zcAW832S7610=9L03U, IP: 65.2.22.171
- 2026-04-27 | Built `breeze_data.py` — Breeze primary data source: historical, F&O, live quotes, session mgmt
- 2026-04-27 | Breeze strategy: primary data source (free, 3yr history, 1sec), Kite only for trading/orders
- 2026-04-27 | Breeze must run from VPS (IP enforced) — test tomorrow when SSH fixed
- 2026-04-27 | Built `data_manager.py` — unified data layer: Breeze primary, Kite fallback, yfinance last resort
- 2026-04-27 | Upgraded `pages/2_Market/1_Historical_Data.py` — Breeze+Kite dual source, added F&O historical tab
- 2026-04-27 | Upgraded `signal_engine.py` — _fetch_ohlcv now uses data_manager (Breeze→Kite→yfinance)

---

## Recent git commits
{recent_commits}

---

## Stats (auto-counted)
- Dashboard pages: **{len(pages)}**
- Core Python files: **{len(list(BASE_DIR.glob("*.py")))}**
- Strategy files: **{len(strategy_files)}**
"""
    return doc


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🔄 Scanning codebase...")
    content = build_claude_md()
    out = BASE_DIR / "CLAUDE.md"
    out.write_text(content, encoding="utf-8")
    print(f"✅ CLAUDE.md updated ({len(content.splitlines())} lines)")
    print(f"   → {out}")
