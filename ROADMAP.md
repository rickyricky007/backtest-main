# Algo Trading System — Production Roadmap

> Path from current state (deployed but unproven) → battle-tested LIVE trading.
> Edit this file freely. Tick boxes as you finish things.
> Last updated: 2026-05-01

---

## 🎯 Where we are now

```
Stage 1: Prototype          ████████████ ✅ Done
Stage 2: Functional MVP     ████████████ ✅ Done
Stage 3: Production-ready   ████░░░░░░░░ ~30% — YOU ARE HERE
Stage 4: Production-hardened░░░░░░░░░░░░ ~5%
Stage 5: Battle-tested      ░░░░░░░░░░░░ Need 6+ months of trading data
```

**Today's status:** infrastructure solid, code mostly clean, strategy unproven.
**Mode:** PAPER only. Do NOT go LIVE until Phase 4 milestones hit.

---

## 📅 Phase 1 — Code Hardening (Week 1–2)

Goal: zero known bugs, every rule respected, every alert path gated.

### Critical (do first)
- [ ] **NSE holiday calendar** — `scheduler._is_market_day()` only checks weekday. Add NSE holiday list (Republic Day, Holi, Eid, Diwali, etc.). Source: `nsepy.holidays()` or hardcoded JSON.
- [ ] **Circuit breaker** — pause trading after N consecutive losses (e.g. 3 SL hits in a row → halt for the day). Add to `risk_manager`.
- [ ] **Order reconciliation** — background job every 5 min: pull open Kite orders, compare to `engine_orders` table, reconcile stuck PENDING/REJECTED states.
- [ ] **Auto Kite token renewal** — `auto_renew_token.py` exists but daily manual login still required. Investigate Kite's OAuth refresh flow OR build a Selenium-based auto-login (with TOTP support since Zerodha mandates 2FA).
- [ ] **Auto Breeze token renewal** — same daily-manual problem. Lower priority than Kite (Kite = orders, Breeze = data only).

### Test coverage
- [ ] Unit tests for `order_manager` (paper fill logic, slippage calc, mode switching)
- [ ] Unit tests for `signal_engine` (`scan_symbol`, `scan_and_trade` happy + sad paths)
- [ ] Unit tests for `strategy_engine` (`on_ticks` flow, regime gate, risk gate)
- [ ] Unit tests for `stop_loss_manager` (trailing logic, exit on tick)
- [ ] Integration test: full signal → risk → order → SL register flow in PAPER mode

### Code-quality cleanup
- [ ] `scheduler.py` — replace custom `_log()` with `logger.get_logger()`
- [ ] `process_guard.py` — replace custom `_log()` with `logger.get_logger()`
- [ ] `kite_data.py` — replace bare `try/except: pass` (lines 39-40, 145-151, 156-166) with proper logging
- [ ] `generate_token.py` — add logger + try/except wrap
- [ ] `breeze_data.py` — replace 8 bare `print()` with logger
- [ ] `update_docs.py` — keep print() (it's a CLI tool, not service)
- [ ] Run `ruff check .` (or similar linter) and fix all warnings
- [ ] Run `mypy --strict` on critical files (risk_manager, order_manager, signal_engine, indicators)

### Architecture
- [ ] Wire **confluence engine** (`signal_engine.py`) into `strategy_engine.py` `ACTIVE_STRATEGIES`. Currently only RSI + SMA on 3 symbols are active. Confluence engine has 56 symbols but isn't running.
- [ ] Decide: keep both `local_store.py` + `db.py` or consolidate. Currently overlapping responsibilities.
- [ ] Fix `update_docs.py` change-log template — entries get duplicated each app start. Make it idempotent.

### Deploy & ops
- [ ] CI pipeline — GitHub Action that runs tests on every push
- [ ] Pre-commit hook — block commits if tests fail or linter complains
- [ ] Monitoring beyond Streamlit — add Telegram-only "system OK" heartbeat every 30 min
- [ ] DB backup — automate daily Supabase export to S3 (currently manual)
- [ ] Second EC2 instance (cold standby) — if Mumbai region has outage, can spin up replica fast

---

## 📊 Phase 2 — Backtest Validation (Week 3)

Goal: prove strategies make money on historical data BEFORE risking capital.

- [ ] Pull 2 years of daily OHLCV for top-50 F&O stocks via Breeze
- [ ] Pull 1 year of 15-min OHLCV for top-10 F&O stocks
- [ ] Run **each strategy** individually:
  - [ ] RSI(14) strategy → win rate, max DD, sharpe, profit factor
  - [ ] SMA(20,50) crossover → same metrics
  - [ ] VWAP strategy → same metrics
  - [ ] ORB strategy → same metrics
  - [ ] Each options strategy → same metrics
- [ ] Run **confluence engine** on top-50 → verify 10-indicator scoring actually beats single strategies
- [ ] **Kill criteria** — drop any strategy with:
  - Win rate < 50%
  - Profit factor < 1.5
  - Max drawdown > 15%
  - Sharpe < 1.0
- [ ] Document survivors in `STRATEGY_REPORT.md` with charts + metrics
- [ ] Re-test survivors on a held-out period (last 3 months) to check for overfitting

---

## 📝 Phase 3 — Paper Trading (Week 4–5)

Goal: 2-3 weeks of live paper trading on real market conditions.

### Setup
- [ ] Run `process_guard.py` 24/7 in PAPER mode
- [ ] Confluence engine scans every 5 min during market hours
- [ ] Telegram master switch ON, all alerts enabled
- [ ] Daily P&L report at 15:45

### Daily checklist (each market day)
- [ ] Morning: confirm 4 services up (`status.sh`)
- [ ] Verify Kite token + Breeze token are valid
- [ ] Check overnight events / news
- [ ] At market close: review trades, write 1-line journal entry per trade

### Validation criteria (must hit ALL before going LIVE)
- [ ] At least 30 paper trades executed
- [ ] Paper P&L matches backtest expectations within ±20%
- [ ] No bugs causing duplicate orders, missed SLs, or stuck positions
- [ ] Slippage model confirmed accurate (compare paper fill prices to actual market)
- [ ] Telegram alerts work end-to-end (didn't miss a single signal)

---

## 💰 Phase 4 — LIVE with 1 lot (Week 6–10)

Goal: 30 days of profitable LIVE trading at minimum size.

### Pre-flight (do not skip)
- [ ] Switch ONE strategy to LIVE mode (start with the best-backtested one)
- [ ] ONE symbol only (most liquid: RELIANCE or NIFTY index futures)
- [ ] ONE lot only (lowest possible position size)
- [ ] Capital allocated: amount you can lose entirely without losing sleep
- [ ] Daily loss limit: 2% of capital
- [ ] Max positions: 1
- [ ] Max orders/day: 5

### Daily ritual
- [ ] Morning: full system check (token, services, ticker, ec2 status)
- [ ] Midday: scan logs for warnings/errors
- [ ] Close: review P&L, journal each trade with emotion + reasoning
- [ ] Weekly: review all trades, calculate week's metrics

### Go/no-go criteria for scaling up
- [ ] 20+ live trades executed
- [ ] Live P&L positive over 30 days
- [ ] No system failures (crashed services, missed orders, stuck positions)
- [ ] Live win rate within ±10% of backtest expectations

---

## 📈 Phase 5 — Scale Up (Week 11+)

Goal: gradually expand exposure while monitoring metrics.

**Scaling rules — change ONE variable at a time:**
- Week 1: 1 lot → 2 lots (same strategy, same symbol)
- Week 2: 2 lots → add second symbol (still same strategy)
- Week 3: add second strategy
- Week 4: 2 lots → 3 lots
- Each step: must show profitable for 2 weeks before next step

**Stop conditions** — pause and review if any of these hit:
- Daily loss limit triggered 2 days in a row
- Weekly P&L negative 2 weeks in a row
- Sharpe ratio drops below 1.0 over rolling 30 days
- Any system bug causes a stuck order or wrong-direction trade

---

## ⚠️ Cardinal rules (never break these)

1. **Money at risk = always test first.** No "small change, won't break anything."
2. **One change at a time.** Strategy + symbol + size all changing simultaneously = no learning.
3. **Daily journal is non-negotiable.** Even one line per trade. Patterns emerge after 30 entries.
4. **Master switch test weekly.** Flip OFF, verify Telegram silent, flip ON. Catches regressions.
5. **Backup before deploy.** Always `git push` before `git pull` on EC2 (so rollback is possible).
6. **Don't trade FOMO.** If a setup wasn't in your backtest, don't take it live.

---

## 🗂 Reference

- Code: `/Users/deva/algo_trading/ricky_1/`
- Project map: `CLAUDE.md` (auto-updated each app start)
- VPS: `ubuntu@65.2.22.171` (`ssh -i ~/Downloads/algotrading-key.pem`)
- Dashboard: http://65.2.22.171
- Telegram bot: configured in `.env`
- Database: Supabase Postgres (primary) + dashboard.sqlite (fallback)

---

## ✅ Already done (reference, don't redo)

- Folder renamed `ricky 1` → `ricky_1`
- VPS IP `65.2.22.171` registered with Zerodha (SEBI-compliant)
- Static IP also whitelisted in Breeze
- Master alert switch + per-alert toggles (`alert_registry.py`)
- All 6 Telegram paths gated through master switch
- 6 critical bugs fixed (signal_engine mode kwarg, order_manager parens, requirements missing deps, etc.)
- 49 print() calls replaced with logger across order_manager, strategy_engine, ticker_service
- Risk manager state DB-persisted (survives restarts)
- Greeks decremented on EXIT
- ticker_service expanded from 3 → 56 symbols + 24h instrument cache
- Dead `rsi_strategy.py` (top level) archived
- 23 unit tests passing (indicators + risk_manager)

---

**Next session:** say _"let's continue with Phase 1"_ — we'll pick the highest-priority unchecked item and start.
