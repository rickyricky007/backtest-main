# Algo Trading System — Project Map
> Auto-generated on **2026-04-26 10:32** — updates automatically every time the app starts.

---

## What this project is
A production-grade algorithmic trading system built on Zerodha Kite API + Streamlit dashboard.
**Owner:** Ricky | **Broker:** Zerodha | **Exchange:** NSE / NFO (F&O)

---

## How to start every session
```bash
cd ~/algo_trading/backtest-main
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

## Dashboard Pages (16 pages across 6 sections)

| Section | Page | Description |
|---------|------|-------------|
| **Account** | `Holdings` | Holdings — full table and export. |
| **Account** | `Positions` | Positions — net vs intraday. |
| **Account** | `Funds` | Funds & margins — raw Kite margin payload. |
| **Market** | `Historical Data` | Historical Data — fetch OHLCV from Kite and display chart + table. |
| **Market** | `Options Chain` | Options Chain Viewer — All F&O Indices & Stocks |
| **Market** | `Charts` | Advanced F&O Charts — Multi-Timeframe with Indicators |
| **Signals** | `Signal Scanner` | Signal Scanner — Live Multi-Symbol Confluence Dashboard |
| **Signals** | `Strategy Hub` | Strategy Hub |
| **Signals** | `FO Dashboard` | F&O Dashboard |
| **Trading** | `ST Paper Trading` | — |
| **Trading** | `FO Paper Trading` | F&O Paper Trading — simulate options/futures trading with real Kite prices. |
| **Trading** | `Backtest` | Backtest Lab |
| **Analytics** | `Strategy PnL` | Strategy P&L Dashboard |
| **Analytics** | `Trade Journal` | Trade Journal |
| **System** | `Chatbot` | Trading Assistant Chatbot — AI-powered chat with live Kite data. |
| **System** | `System Status` | System Status — Control Room |

---

## File Map

### Core
| File | Purpose | Lines |
|------|---------|-------|
| `alert_engine.py` | Alert engine — Telegram notifications for price and P&L alerts. | 91 |
| `app.py` | Trading dashboard — navigation shell (run with: streamlit run app.py). | 64 |
| `auth_streamlit.py` | Streamlit helpers: Kite session status and management (terminal-auth flow). | 69 |
| `config.py` | config.py — Centralised environment variable loader | 99 |
| `generate_token.py` | Exchange a request_token for an access token and save to .kite_access_token. | 22 |
| `home.py` | Overview — Zerodha Kite snapshot home page. | 188 |
| `kite_data.py` | Shared Zerodha Kite + market data helpers. | 201 |
| `logger.py` | Central Logger — Algo Trading System | 73 |

### Live Data
| File | Purpose | Lines |
|------|---------|-------|
| `market_data.py` | Market Data — Phase 3 Complete | 353 |
| `ticker_service.py` | Live Ticker Service — Zerodha KiteTicker WebSocket | 146 |

### Signal & Intelligence Layer
| File | Purpose | Lines |
|------|---------|-------|
| `fo_symbols.py` | F&O Universe — Complete Symbol Registry | 155 |
| `indicators.py` | Indicators Engine — Weighted Confluence Scoring System | 627 |
| `regime_filter.py` | Regime Filter | 276 |
| `signal_engine.py` | Signal Engine — Multi-Symbol Confluence Scanner | 402 |
| `strategy_engine.py` | Strategy Engine | 324 |

### Strategy Layer
| File | Purpose | Lines |
|------|---------|-------|
| `strategies/base_strategy.py` | BaseStrategy — template every strategy must follow. | 145 |
| `strategies/options_strategy.py` | Options Strategies | 359 |
| `strategies/orb_strategy.py` | Opening Range Breakout (ORB) Strategy | 159 |
| `strategies/rsi_strategy.py` | RSI Strategy | 145 |
| `strategies/sma_strategy.py` | SMA Crossover Strategy | 108 |
| `strategies/vwap_strategy.py` | VWAP Strategy | 129 |

### Execution Layer
| File | Purpose | Lines |
|------|---------|-------|
| `order_manager.py` | Order Manager — Phase 1 Complete | 620 |
| `position_sizer.py` | Position Sizer | 160 |
| `risk_manager.py` | Risk Manager — Phase 2 Complete | 240 |
| `stop_loss_manager.py` | Stop Loss Manager | 298 |

### Backtesting
| File | Purpose | Lines |
|------|---------|-------|
| `backtest_engine.py` | Backtest Engine — Phase 5 | 478 |
| `backtest_runner.py` | Long-only backtests on OHLCV loaded from SQLite (next-bar open execution). | 190 |

### Infrastructure
| File | Purpose | Lines |
|------|---------|-------|
| `auto_renew_token.py` | Auto Token Renewal | 193 |
| `db.py` | Database Layer — Supabase PostgreSQL (primary) + SQLite (local fallback) | 379 |
| `process_guard.py` | Watchdog — Auto Restart on Crash | 240 |
| `scheduler.py` | Scheduler — Scheduled Jobs for Algo Trading | 255 |

---

## Database (`dashboard.sqlite`)
| Table | Description |
|-------|-------------|
| `historical_bars` | — |
| `strategies` | — |
| `sqlite_sequence` | — |
| `backtest_runs` | — |
| `strategy_groups` | — |
| `strategy_group_members` | — |
| `fo_portfolio` | — |
| `fo_trades` | — |
| `alerts` | — |
| `app_settings` | — |
| `sma_signals` | — |
| `strategy_trades` | Strategy signal log with P&L |
| `engine_orders` | All orders (paper + live) with fill info |
| `trade_journal` | Manual trade diary entries |
| `sl_positions` | Active stop-loss positions |

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

---

## Recent git commits
- 77c1eaa feat: Supabase DB, Telegram alerts, backups, token monitor, daily report, unit tests, page reorganisation
- ceed084 feat: Charts, Options Chain all F&O, Chatbot upgrade, market intelligence
- ab31228 Add signal engine (10-indicator confluence) + Signal Scanner dashboard
- 44f07b5 changes style
- df2e80e "Fix db.py: switch from PostgreSQL to SQLite, add central logger, fix error handling"

---

## Stats (auto-counted)
- Dashboard pages: **16**
- Core Python files: **35**
- Strategy files: **6**
