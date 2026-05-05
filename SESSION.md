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

**Last updated:** 2026-05-05 (IST) — journal below covers 2026-05-04 and 2026-05-05  
**Agent / tool:** `cursor-composer`

### Done — **2026-05-04** (`cursor-composer`)

- **Light Trades UI simplification:** Removed the **Rule toggles** block (group checkboxes + backtest caption). Control is via **Apply each parameter value (per field)** only; **`param_apply`** + **`light_nifty_rsi`** / **`light_l1_backtest`** unchanged in spirit.
- **OTM — index points:** Separate **min / max** fields and Apply rows (**OTM — index points from spot**); labels clarified (CE/PE vs spot).
- **Restore defaults:** Single **Restore defaults** beside **Parameters** (outside form so it runs immediately + rerun).
- **Save behaviour:** Form **Save** keeps existing **`use_*`** rule-group flags from loaded **`cfg`** (no accidental flip when group toggles were removed) — change **`use_*`** via **Restore defaults**, named profiles, or code.
- **`L1_PARAM_APPLY_KEYS`:** Local tuple on **`4_Light_Strategies.py`** (must stay aligned with **`PARAM_APPLY_KEYS`** in **`light_strategy_config.py`**) to avoid stale **`ImportError`** on **`PARAM_APPLY_KEYS`** import.

### Done — **2026-05-05** (`cursor-composer`)

- **OTM strike steps (reverted):** Implemented **`otm_distance_*` as strike steps from ATM** + **`otm_points_*`**, then **removed** strike-step fields and logic per request; kept **`otm_points_min/max`** only. Legacy JSON: **`otm_distance_*` points-only** still migrates to **`otm_points_*`** in **`LightNiftyRSIConfig.from_dict`**.
- **Entry / exit time windows:** Config + UI: **`use_entry_window`**, **`use_exit_window`**, **`exit_window_start`**, **`exit_window_end`**. **Both toggles off** ⇒ no IST clock band on **new entries** or on **TP / time stop / RSI** exits; **`light_nifty_rsi`** + **`light_l1_backtest`**: **EOD** + **stop loss** still evaluated when enabled (not gated by exit window).
- **Apply section — bulk toggles:** **Apply** expander placed **above** the main form (**Streamlit** forbids **`st.button` inside `st.form`**). Each heading (**RSI**, **OTM**, **Premium**, **Exit / time**, **Risk / size**) has **All on** / **All off** for that section’s **`param_apply`** keys; **Save configuration** still required to persist.
- **Docs / handoff:** **`AGENTS.md`** updated for **`light_l1_config`** (time windows, OTM, profiles); **`SESSION.md`** / **`CLAUDE.md`** sync clarified — regenerate **`CLAUDE.md`** with **`python update_docs.py`** after **`SESSION.md`** edits.

### Same workstream (recent; includes pre–05-04)

- **Trade permission:** **`light_l1_trade_permission`** — OFF blocks **new** CE/PE **BUY**; **EXIT** for open leg still runs; UI toggle + **`check_light_ready`** + **`AGENTS.md`**.
- **`param_apply`:** Full wiring on **`LightNiftyRSIConfig`**; strategy + sim honour masks.
- **Mission control row** on Light Trades; **`light_l1_last_order()`**; caps caption with entry/exit window ON/OFF.
- **Named profiles:** **`light_l1_profiles`** (max 20), **`light_strategy_config`** load/save/delete, UI expander.
- **Infra / ops:** SQLite **`engine_orders`** migration in **`db.py`**; Streamlit **`width`** vs deprecated container width; **`psycopg2-binary`** / Postgres when **`DATABASE_URL`** set; **`deploy/local_startup.sh`**, **`make local-start`**; **`process_guard`** free Streamlit port; **`Makefile`** **`status`** / **`light-status`**.
- **Phase 2 / analytics:** **`order_manager._log`**, fills/slippage; **`option_quote_iv`**; fills vs assumptions; **`mid_premium_assumption`** on signals.

**Earlier in same workstream**
- **Product priorities** block (this file); **`ROADMAP2`** Phase 2 tracking.

**ROADMAP2 Phase 2 — still open** (see `ROADMAP2.md`; operator may treat some items as optional — see **Product priorities** above)
- [ ] **Option chain history** — replay real premia *(optional; sim backtest remains in `light_l1_backtest.py`)*.
- [ ] **Pick best 2 configs → paper ~2 weeks** — roadmap **manual** step; **override OK** if you go straight to small LIVE / skip extended paper.

**Next**
- Run **`make local-start`** and verify login/token flow + watchdog startup from one command; confirm dashboard URL/port printed by `process_guard`.
- Run **`make status`** before market; keep **PAPER** until you intentionally switch **LIVE** in the form.

**Blockers**
- None.

**Files touched** (2026-05-04 / 05-05 Light L1 + docs)
- `ricky_1/light_strategy_config.py`
- `ricky_1/strategies/light_nifty_rsi.py`
- `ricky_1/light_l1_backtest.py`
- `ricky_1/pages/3_Signals/4_Light_Strategies.py`
- `ricky_1/AGENTS.md`
- `ricky_1/SESSION.md`
- `ricky_1/CLAUDE.md` (regenerate: `cd ricky_1 && python update_docs.py`)

**Files touched** (same sprint — infra / readiness)
- `ricky_1/scripts/check_light_ready.py`
- `ricky_1/process_guard.py`
- `ricky_1/deploy/local_startup.sh`
- `ricky_1/db.py`
- `ricky_1/Makefile`
- `ricky_1/light_fill_quality.py` (`light_l1_last_order`)

---

## Honest note about “automatic”

- **Cursor** can load rules from **`.cursor/rules/`** when you use the agent — **no extra paste**.
- **Web Claude / ChatGPT** do **not** see your disk until you **upload** or **paste** — send them **`SESSION.md`** (and **`AGENTS.md`** if long session).
- Nothing updates **by itself at midnight** — someone (you or AI) runs **“update SESSION.md”** when you finish work.
- After **`SESSION.md`** lists **Agent / tool**, opening the dashboard or running **`python update_docs.py`** copies that into **`CLAUDE.md`** (see the second line under the title).
