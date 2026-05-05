"""
Light Strategy L1 — NIFTY RSI options (CE/PE), configurable via DB + dashboard.
===============================================================================
Subscribes to **NIFTY 50** index ticks; builds 5-minute candles; RSI entries;
selects weekly NIFTY options by OTM index points + premium band. Manages exits via
live quotes (index ticks alone do not carry option prices — SL manager is not
used for open option legs).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

import kite_data as kd
from logger import get_logger
from light_strategy_config import (
    LightNiftyRSIConfig,
    is_light_l1_enabled,
    is_light_l1_trade_permission,
    load_config,
    load_day_state,
    param_apply_on,
    save_day_state,
)
from strategies.base_strategy import BaseStrategy, Signal

log = get_logger("light_nifty_rsi")

IST = ZoneInfo("Asia/Kolkata")
NIFTY_FNO_NAME = "NIFTY"
INDEX_SYMBOL = "NIFTY 50"
QUOTE_COOLDOWN_SEC = 1.0


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = str(s).strip().split(":")
    h = int(parts[0]) if parts else 9
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _wilder_rsi(closes: list[float], period: int) -> float:
    if len(closes) < period + 1:
        return 50.0
    arr = np.array(closes[-(period * 3) :])
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _otm_distance(opt_type: str, strike: float, spot: float) -> float:
    if opt_type == "CE":
        return max(0.0, strike - spot)
    return max(0.0, spot - strike)


def _expiry_as_date(exp: Any) -> date:
    if hasattr(exp, "date"):
        return exp.date()
    return exp  # type: ignore[return-value]


def _pick_option_contract(
    kite: Any,
    cfg: LightNiftyRSIConfig,
    opt_type: str,
    spot: float,
) -> tuple[str, float, int] | None:
    """Return (tradingsymbol, last_price, contract lot_size from instrument) or None."""
    try:
        inst = kite.instruments("NFO")
    except Exception:
        log.warning("instruments(NFO) failed", exc_info=True)
        return None

    today = date.today()
    rows = [
        r
        for r in inst
        if r.get("name") == NIFTY_FNO_NAME and r.get("instrument_type") == opt_type
    ]
    if not rows:
        return None

    future_exp = sorted({_expiry_as_date(r["expiry"]) for r in rows if _expiry_as_date(r["expiry"]) >= today})
    if not future_exp:
        return None
    nearest = future_exp[0]

    strike_rows = [r for r in rows if _expiry_as_date(r["expiry"]) == nearest]
    eff_pt_min = cfg.otm_points_min if param_apply_on(cfg, "otm_points_min") else 0.0
    eff_pt_max = cfg.otm_points_max if param_apply_on(cfg, "otm_points_max") else 1e9
    if cfg.use_otm_distance_filter:
        candidates: list[dict[str, Any]] = []
        for r in strike_rows:
            strike = float(r["strike"])
            pts = _otm_distance(opt_type, strike, spot)
            if eff_pt_min <= pts <= eff_pt_max:
                candidates.append(r)
    else:
        candidates = list(strike_rows)

    if not candidates:
        return None

    candidates.sort(key=lambda r: abs(float(r["strike"]) - spot))

    def quote_batch(keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i in range(0, len(keys), 400):
            chunk = keys[i : i + 400]
            try:
                q = kite.quote(chunk)
                if q:
                    out.update(q)
            except Exception:
                log.warning("quote batch failed", exc_info=True)
        return out

    keys = [f"NFO:{r['tradingsymbol']}" for r in candidates]
    quotes = quote_batch(keys)

    for r in candidates:
        sym = r["tradingsymbol"]
        key = f"NFO:{sym}"
        row = quotes.get(key) or {}
        depth = row.get("depth") or {}
        ltp = row.get("last_price") or row.get("ohlc", {}).get("close")
        if ltp is None:
            buy = depth.get("buy", [])
            sell = depth.get("sell", [])
            if buy and sell:
                ltp = (float(buy[0]["price"]) + float(sell[0]["price"])) / 2
        if ltp is None:
            continue
        ltp = float(ltp)
        if cfg.use_premium_band:
            eff_pmin = cfg.min_premium if param_apply_on(cfg, "min_premium") else 0.0
            eff_pmax = cfg.max_premium if param_apply_on(cfg, "max_premium") else 1e9
            if not (eff_pmin <= ltp <= eff_pmax):
                continue
        lot = int(r.get("lot_size") or 50)
        return (sym, ltp, lot)
    return None


class LightNiftyRSIStrategy(BaseStrategy):
    """
    Mean-reversion style: buy CE on RSI oversold (cash-index RSI), PE on overbought.
    Live mode and thresholds come from `light_strategy_config.load_config()`.
    """

    manages_own_exits = True

    def __init__(self, enabled: bool = True):
        super().__init__(
            symbol=INDEX_SYMBOL,
            exchange="NSE",
            quantity=1,
            mode="PAPER",
            enabled=enabled,
        )
        self._rsi_closes: list[float] = []
        self._bucket_start: datetime | None = None
        self._bucket_close: float = 0.0
        self._prev_rsi: float | None = None

        self._open_leg: dict[str, Any] | None = None
        self._last_quote_ts: float = 0.0
        self._last_option_ltp: float = 0.0

    @property
    def name(self) -> str:
        return "Light_NIFTY_RSI"

    @property
    def description(self) -> str:
        return "Light L1 — NIFTY 5m RSI, weekly options (CE oversold / PE overbought)"

    def on_start(self) -> None:
        try:
            to_d = datetime.now(IST).strftime("%Y-%m-%d")
            from_d = (datetime.now(IST) - timedelta(days=7)).strftime("%Y-%m-%d")
            df = kd.fetch_historical(INDEX_SYMBOL, "NSE", "5minute", from_d, to_d)
            if df is not None and not df.empty and "close" in df.columns:
                for x in df["close"].tolist():
                    self._rsi_closes.append(float(x))
                self._rsi_closes = self._rsi_closes[-500:]
                log.info(f"Light L1 warmed up with {len(self._rsi_closes)} five-minute closes")
        except Exception:
            log.warning("Light L1 historical warmup failed (will build from live ticks)", exc_info=True)

    def on_stop(self) -> None:
        self._open_leg = None

    def _now_ist(self) -> datetime:
        return datetime.now(IST)

    def _in_entry_window(self, cfg: LightNiftyRSIConfig, now: datetime) -> bool:
        sh, sm = _parse_hhmm(cfg.entry_window_start)
        eh, em = _parse_hhmm(cfg.entry_window_end)
        t = now.time()
        start = datetime.now(IST).replace(hour=sh, minute=sm, second=0, microsecond=0).time()
        end = datetime.now(IST).replace(hour=eh, minute=em, second=0, microsecond=0).time()
        return start <= t <= end

    def _in_exit_window(self, cfg: LightNiftyRSIConfig, now: datetime) -> bool:
        sh, sm = _parse_hhmm(cfg.exit_window_start)
        eh, em = _parse_hhmm(cfg.exit_window_end)
        t = now.time()
        start = datetime.now(IST).replace(hour=sh, minute=sm, second=0, microsecond=0).time()
        end = datetime.now(IST).replace(hour=eh, minute=em, second=0, microsecond=0).time()
        return start <= t <= end

    def _eod_exit_due(self, cfg: LightNiftyRSIConfig, now: datetime) -> bool:
        eh, em = _parse_hhmm(cfg.eod_squareoff_time)
        cutoff = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        return now >= cutoff

    def _feed_five_min_close(self, price: float, now: datetime) -> None:
        cur_bucket = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
        if self._bucket_start is None:
            self._bucket_start = cur_bucket
            self._bucket_close = price
            return
        if cur_bucket > self._bucket_start:
            self._rsi_closes.append(self._bucket_close)
            if len(self._rsi_closes) > 500:
                self._rsi_closes.pop(0)
            self._bucket_start = cur_bucket
            self._bucket_close = price
        else:
            self._bucket_close = price

    def _option_quote(self, tradingsymbol: str) -> float | None:
        now_m = time.monotonic()
        if now_m - self._last_quote_ts < QUOTE_COOLDOWN_SEC:
            return self._last_option_ltp or None
        self._last_quote_ts = now_m
        try:
            kite = kd.kite_client()
            q = kite.quote([f"NFO:{tradingsymbol}"])
            row = q.get(f"NFO:{tradingsymbol}", {})
            p = row.get("last_price") or row.get("ohlc", {}).get("close")
            if p is not None:
                self._last_option_ltp = float(p)
                return self._last_option_ltp
        except Exception:
            log.warning(f"quote failed for {tradingsymbol}", exc_info=True)
        return None

    def _maybe_exit(
        self,
        cfg: LightNiftyRSIConfig,
        rsi: float,
        now: datetime,
    ) -> Signal | None:
        leg = self._open_leg
        if not leg:
            return None

        ltp = self._option_quote(leg["symbol"])
        if ltp is None:
            ltp = float(leg.get("entry_price", 0))

        entry = float(leg["entry_price"])
        opt_type = leg["opt_type"]

        if cfg.use_exit_eod and param_apply_on(cfg, "eod_squareoff_time") and self._eod_exit_due(cfg, now):
            self._open_leg = None
            return self._exit_signal(leg, ltp, "EOD square-off", cfg)

        in_exit_win = (not cfg.use_exit_window) or self._in_exit_window(cfg, now)

        if in_exit_win and cfg.use_exit_time_stop and param_apply_on(cfg, "time_stop_min"):
            elapsed_min = (now - leg["entry_time"]).total_seconds() / 60.0
            if elapsed_min >= cfg.time_stop_min:
                self._open_leg = None
                return self._exit_signal(leg, ltp, f"Time stop ({cfg.time_stop_min} min)", cfg)

        if in_exit_win and cfg.use_exit_profit_target and param_apply_on(cfg, "profit_target_pct"):
            tp = entry * (1.0 + cfg.profit_target_pct / 100.0)
            if ltp >= tp:
                self._open_leg = None
                return self._exit_signal(leg, ltp, f"Profit target +{cfg.profit_target_pct}%", cfg)

        if cfg.use_exit_stop_loss and param_apply_on(cfg, "stop_loss_pct"):
            sl = entry * (1.0 - cfg.stop_loss_pct / 100.0)
            if ltp <= sl:
                self._open_leg = None
                return self._exit_signal(leg, ltp, f"Stop loss -{cfg.stop_loss_pct}%", cfg)

        if in_exit_win and cfg.use_exit_rsi:
            if opt_type == "CE" and param_apply_on(cfg, "rsi_exit_ce_above") and rsi > cfg.rsi_exit_ce_above:
                self._open_leg = None
                return self._exit_signal(leg, ltp, f"RSI exit CE (RSI={rsi} > {cfg.rsi_exit_ce_above})", cfg)
            if opt_type == "PE" and param_apply_on(cfg, "rsi_exit_pe_below") and rsi < cfg.rsi_exit_pe_below:
                self._open_leg = None
                return self._exit_signal(leg, ltp, f"RSI exit PE (RSI={rsi} < {cfg.rsi_exit_pe_below})", cfg)

        return None

    def _exit_signal(self, leg: dict[str, Any], price: float, reason: str, cfg: LightNiftyRSIConfig) -> Signal:
        entry = float(leg["entry_price"])
        win = (price - entry) * int(leg["qty"])
        today = self._now_ist().strftime("%Y-%m-%d")
        st = load_day_state(today)
        if win < 0:
            st.consecutive_losses += 1
            lim = cfg.max_consecutive_losses if param_apply_on(cfg, "max_consecutive_losses") else 999
            if st.consecutive_losses >= lim:
                st.halted = True
        else:
            st.consecutive_losses = 0
        save_day_state(st)

        self._signal_count += 1
        return Signal(
            strategy=self.name,
            symbol=leg["symbol"],
            exchange="NFO",
            action="EXIT",
            quantity=int(leg["qty"]),
            price=float(price),
            reason=reason,
            meta={
                "entry_price": entry,
                "opt_type": leg["opt_type"],
                "pnl_per_lot_approx": round(win, 2),
                "mid_premium_assumption": round(
                    (cfg.min_premium + cfg.max_premium) / 2.0, 2
                ),
            },
        )

    def on_tick(self, tick: dict[str, Any]) -> Signal | None:
        if not self.enabled or not is_light_l1_enabled():
            return None

        cfg = load_config()
        self.mode = cfg.mode

        price = tick.get("last_price")
        if not price:
            return None
        price = float(price)

        now = self._now_ist()
        today = now.strftime("%Y-%m-%d")

        self._feed_five_min_close(price, now)

        period = max(2, int(cfg.rsi_period if param_apply_on(cfg, "rsi_period") else 14))
        if len(self._rsi_closes) < period + 1:
            return None

        rsi = _wilder_rsi(self._rsi_closes, period)

        day_state = load_day_state(today)
        if day_state.halted:
            if self._open_leg:
                return self._maybe_exit(cfg, rsi, now)
            return None

        if self._open_leg:
            ex = self._maybe_exit(cfg, rsi, now)
            if ex:
                return ex

        if self._open_leg:
            return None

        if not is_light_l1_trade_permission():
            self._prev_rsi = rsi
            return None

        max_day = cfg.max_trades_per_day if param_apply_on(cfg, "max_trades_per_day") else 999
        if day_state.trades_today >= max_day:
            self._prev_rsi = rsi
            return None

        if cfg.use_entry_window and not self._in_entry_window(cfg, now):
            self._prev_rsi = rsi
            return None

        try:
            kite = kd.kite_client()
        except Exception:
            log.warning("kite_client unavailable", exc_info=True)
            self._prev_rsi = rsi
            return None

        prev = self._prev_rsi
        self._prev_rsi = rsi

        if prev is None:
            return None

        signal: Signal | None = None

        ce_cross = (
            param_apply_on(cfg, "rsi_buy_ce_below")
            and prev >= cfg.rsi_buy_ce_below
            and rsi < cfg.rsi_buy_ce_below
        )
        pe_cross = (
            param_apply_on(cfg, "rsi_buy_pe_above")
            and prev <= cfg.rsi_buy_pe_above
            and rsi > cfg.rsi_buy_pe_above
        )

        if ce_cross and not pe_cross:
            picked = _pick_option_contract(kite, cfg, "CE", price)
            if picked:
                sym, ltp, lot_unit = picked
                lots = int(cfg.lot_size) if param_apply_on(cfg, "lot_size") else 1
                qty = lots * lot_unit
                self._open_leg = {
                    "symbol": sym,
                    "opt_type": "CE",
                    "entry_price": ltp,
                    "entry_time": now,
                    "qty": qty,
                }
                day_state.trades_today += 1
                save_day_state(day_state)
                self._signal_count += 1
                mid_sim = round((cfg.min_premium + cfg.max_premium) / 2.0, 2)
                signal = Signal(
                    strategy=self.name,
                    symbol=sym,
                    exchange="NFO",
                    action="BUY",
                    quantity=qty,
                    price=float(ltp),
                    reason=f"Light L1 CE — RSI crossed below {cfg.rsi_buy_ce_below} (RSI={rsi})",
                    meta={
                        "spot": price,
                        "rsi": rsi,
                        "opt_type": "CE",
                        "mid_premium_assumption": mid_sim,
                    },
                )

        elif pe_cross and not ce_cross:
            picked = _pick_option_contract(kite, cfg, "PE", price)
            if picked:
                sym, ltp, lot_unit = picked
                lots = int(cfg.lot_size) if param_apply_on(cfg, "lot_size") else 1
                qty = lots * lot_unit
                self._open_leg = {
                    "symbol": sym,
                    "opt_type": "PE",
                    "entry_price": ltp,
                    "entry_time": now,
                    "qty": qty,
                }
                day_state.trades_today += 1
                save_day_state(day_state)
                self._signal_count += 1
                mid_sim = round((cfg.min_premium + cfg.max_premium) / 2.0, 2)
                signal = Signal(
                    strategy=self.name,
                    symbol=sym,
                    exchange="NFO",
                    action="BUY",
                    quantity=qty,
                    price=float(ltp),
                    reason=f"Light L1 PE — RSI crossed above {cfg.rsi_buy_pe_above} (RSI={rsi})",
                    meta={
                        "spot": price,
                        "rsi": rsi,
                        "opt_type": "PE",
                        "mid_premium_assumption": mid_sim,
                    },
                )

        elif ce_cross and pe_cross:
            log.info("Light L1: CE and PE cross same tick — skipped (ambiguous)")

        if signal:
            self._last_signal = signal

        return signal
