# Algo Trading System — Project Map

## What this project is
A production-grade algorithmic trading system built on Zerodha Kite API + Streamlit dashboard.
Owner: Ricky | Broker: Zerodha | Exchange: NSE / NFO (F&O)

## How to start every session
```bash
cd backtest-main
source venv/bin/activate          # activate Python environment
python generate_token.py          # generate today's Kite access token (manual step, once per day)
python process_guard.py           # starts dashboard + strategy engine + ticker (keeps them alive)
# OR start individually:
streamlit run app.py              # dashboard only
python ticker_service.py          # live WebSocket prices
python strategy_engine.py         # strategy execution
python scheduler.py               # scheduled jobs (08:45 reminder, EOD report, DB backup)
```

## Environment (.env)
| Key | Description |
|-----|-------------|
| `API_KEY` | Kite API key (also readable as `KITE_API_KEY`) |
| `API_SECRET` | Kite API secret (also `KITE_API_SECRET`) |
| `TELEGRAM_TOKEN` | Telegram bot token (also `TELEGRAM_BOT_TOKEN`) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `ANTHROPIC_API_KEY` | Claude API key (for chatbot page) |

**All keys are unified via `config.py` — import `cfg` from there.**

## File map

### Core
| File | Purpose |
|------|---------|
| `app.py` | Streamlit home page — index prices, setup instructions |
| `kite_data.py` | Kite REST wrapper + ticker_data.json reader |
| `config.py` | Env var loader — handles old/new key naming |
| `auth_streamlit.py` | Sidebar Kite session status widget |
| `generate_token.py` | Manual Kite token generator (run once per day) |
| `alert_engine.py` | Telegram alert helpers |

### Live Data
| File | Purpose |
|------|---------|
| `ticker_service.py` | KiteTicker WebSocket → writes `ticker_data.json` every tick |
| `market_data.py` | Options chain, IV, Greeks, market depth, futures basis |
| `ticker_data.json` | Written by ticker_service, read by dashboard (< 10s = live) |

### Strategy Layer
| File | Purpose |
|------|---------|
| `strategies/base_strategy.py` | `BaseStrategy` ABC + `Signal` dataclass |
| `strategies/rsi_strategy.py` | RSI crossover (Wilder's smoothing) |
| `strategies/sma_strategy.py` | Golden/Death cross (fast vs slow MA) |
| `strategies/vwap_strategy.py` | VWAP crossover, intraday, resets daily |
| `strategies/orb_strategy.py` | Opening Range Breakout (first N minutes) |
| `strategies/options_strategy.py` | Short Straddle, Short Strangle, Long Straddle |
| `strategy_engine.py` | Central brain — ticks → signals → orders |

### Execution
| File | Purpose |
|------|---------|
| `order_manager.py` | 6 order types, PAPER + LIVE modes, SQLite log |
| `stop_loss_manager.py` | Trailing SL, target exits, auto-order on breach |
| `risk_manager.py` | Daily loss limits, Greeks exposure, position sizing |
| `position_sizer.py` | Fixed risk, Kelly Criterion, % capital sizing |

### Backtesting
| File | Purpose |
|------|---------|
| `backtest_engine.py` | `BacktestEngine` with run(), walk_forward(), optimize() |
| `backtest_runner.py` | CLI backtest runner |

### Infrastructure
| File | Purpose |
|------|---------|
| `process_guard.py` | Keeps dashboard + engine + ticker alive (auto-restart) |
| `scheduler.py` | Cron-style jobs: token reminder, EOD report, DB backup |
| `auto_renew_token.py` | Telegram alert for token renewal + API validation |

### Dashboard Pages (Streamlit)
| Page | Route | Description |
|------|-------|-------------|
| app.py | `/` | Overview — index prices, Kite status |
| 1_Holdings | `/Holdings` | Current holdings from Kite |
| 2_Positions | `/Positions` | Open positions |
| 3_Funds | `/Funds` | Available margin |
| 4_Historical_data | `/Historical_data` | OHLCV chart + CSV download |
| 5_Strategies | `/Strategies` | Strategy browser |
| 6_Chatbot | `/Chatbot` | AI chatbot (Claude) |
| 7_ST_Paper_Trading | `/ST_Paper_Trading` | Stock paper trading |
| 8_FO_Paper_Trading | `/FO_Paper_Trading` | F&O paper trading |
| 9_RSI_Strategy | `/RSI_Strategy` | RSI strategy UI |
| 10_Sma_Strategy | `/Sma_Strategy` | SMA strategy UI |
| **11_Options_Chain** | `/Options_Chain` | Live options chain + straddle launcher |
| **12_FO_Dashboard** | `/FO_Dashboard` | IV rank, Greeks, max pain, futures basis |
| **13_Strategy_PnL** | `/Strategy_PnL` | Strategy P&L + equity curve + order book |
| **14_Trade_Journal** | `/Trade_Journal` | Personal trade diary with analytics |
| **15_System_Status** | `/System_Status` | Control room — service health + log viewer |
| **16_Backtest** | `/Backtest` | Backtest lab — run/optimise/walk-forward |

Bold = built in this session.

### Database (`dashboard.sqlite`)
| Table | Contents |
|-------|---------|
| `engine_orders` | All orders (paper + live) with fill info |
| `strategy_trades` | Strategy signal log with P&L |
| `sl_positions` | Active stop-loss positions |
| `trade_journal` | Manual trade diary entries |

## Adding a new strategy
1. Create `strategies/my_strategy.py` inheriting `BaseStrategy`
2. Implement `name`, `description`, `on_tick()` (return `Signal` or `None`)
3. Add to `strategies/__init__.py` exports
4. Add to `ACTIVE_STRATEGIES` in `strategy_engine.py`
5. Add to `STRATEGY_MAP` in `pages/16_Backtest.py` for backtesting UI

## Key architectural decisions
- **Terminal-only auth**: no browser login automation — run `python generate_token.py` once per morning
- **WebSocket ticks**: `ticker_service.py` writes to JSON file; dashboard reads it (no shared memory needed)
- **2-second dashboard refresh**: UI lag only — strategy engine reacts on every tick (5–50ms)
- **Centralised engine**: `strategy_engine.py` routes ticks to all strategies; add strategies by editing one list
- **PAPER / LIVE modes**: all strategies and order manager respect this flag; switch per-strategy in `strategy_engine.py`
