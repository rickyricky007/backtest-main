# Working session — handoff

**This file is manual.** Update it at the **end** of each session so the next chat (you + any AI) starts aligned.

**Suggested trigger phrases:** `continue` · `start` · `update SESSION.md`

---

## Format (keep these headings)

| Field | Description |
|--------|--------------|
| **Last updated** | ISO date + who ran the session |
| **Agent / tool** | Who did the work (see naming below) |
| **Done this session** | Bullets — shipped or decided |
| **Next** | One concrete next step |
| **Blockers** | None, or list |
| **Files touched** | Paths only |

### Agent naming (pick one per session)

Use so logs stay searchable:

| Tool | Example label |
|------|----------------|
| Cursor (this IDE AI) | `cursor-composer` or `cursor-agent` |
| Claude Sonnet | `claude-sonnet-4.6` |
| Claude Opus | `claude-opus-4.7` |
| You alone | `human` |

---

## Product priorities — operator context *(update when this shifts)*

- **Experience:** Not treating as a beginner; roughly **1.5 yrs** active trading. **Paper + backtest** are sometimes **formality** — you may **skip or override** when you choose; defaults in docs stay **PAPER / conservative** unless you say otherwise.
- **Near-term:** **Light L1** + **dashboard/UI** + **product ready for real-time execution** (within your risk rules). Ship usable paths **before** heavy investment in extra strategies or exhaustive research mode.
- **Later / parallel:** Additional light slots (**L2/L3**), **Phase 3** group toggles, **deeper backtest / option-chain replay** — after L1 is stable in live workflow.
- **Tracking:** Keep **`SESSION.md`** (done / next / pending) + **`ROADMAP2.md`** checkboxes so “what we finished vs what’s open” stays visible for you and any AI.

---

## Current session (latest)

**Last updated:** 2026-05-02 · **~19:40 IST** (Indian Standard Time, Asia/Kolkata)  
**Agent / tool:** `cursor-composer`

**Done this session** *(agent: **`cursor-composer`**)*
- **Light L1 rule-group toggles:** Eight `use_*` booleans on **`LightNiftyRSIConfig`** — entry window, OTM filter, premium band; exits EOD / time / TP / SL / RSI. Form section **Rule toggles** on Light Trades; save requires ≥1 exit rule. **`light_nifty_rsi`** + **`light_l1_backtest`** honour the same flags (backtest caption: OTM/premium affect live pick only).
- **Light Trades — mission control:** **LIVE** error banner, 6-tile row (mode, engine, trades, halted, consecutive losses, last order time + detail), caps caption, CLI hint.
- **Named profiles:** **`light_l1_profiles`** in **`app_settings`** (max 20) — `load/save/delete` in **`light_strategy_config.py`**, expander on Light Trades to apply/save/delete.
- **Readiness:** **`scripts/check_light_ready.py`**, **`Makefile`** targets **`status` / `light-status`** (run from **`ricky_1/`**).
- **`light_fill_quality.light_l1_last_order()`** for last-row mission control.
- **`AGENTS.md`** — document **`light_l1_profiles`**.

**Earlier in same workstream**
- **Phase 2 tracking:** **`order_manager._log`** + fill columns; **`kite_data.option_quote_iv`**; **Fills vs assumptions** table; **`mid_premium_assumption`** on signals; **Product priorities** block in this file.

**ROADMAP2 Phase 2 — still open** (see `ROADMAP2.md`; operator may treat some items as optional — see **Product priorities** above)
- [ ] **Option chain history** — replay real premia *(optional; sim backtest remains in `light_l1_backtest.py`)*.
- [ ] **Pick best 2 configs → paper ~2 weeks** — roadmap **manual** step; **override OK** if you go straight to small LIVE / skip extended paper.

**Next**
- Run **`make status`** (from **`ricky_1/`**) before market; exercise **mission control** + **named profiles**; keep **PAPER** until you intentionally switch **LIVE** in the form.

**Blockers**
- None.

**Files touched** (this batch)
- `ricky_1/light_strategy_config.py`
- `ricky_1/strategies/light_nifty_rsi.py`
- `ricky_1/light_l1_backtest.py`
- `ricky_1/pages/3_Signals/4_Light_Strategies.py`
- `ricky_1/AGENTS.md`
- `ricky_1/SESSION.md`
- `ricky_1/CLAUDE.md` (via `update_docs.py` after this edit)

---

## Honest note about “automatic”

- **Cursor** can load rules from **`.cursor/rules/`** when you use the agent — **no extra paste**.
- **Web Claude / ChatGPT** do **not** see your disk until you **upload** or **paste** — send them **`SESSION.md`** (and **`AGENTS.md`** if long session).
- Nothing updates **by itself at midnight** — someone (you or AI) runs **“update SESSION.md”** when you finish work.
- After **`SESSION.md`** lists **Agent / tool**, opening the dashboard or running **`python update_docs.py`** copies that into **`CLAUDE.md`** (see the second line under the title).
