"""
Light Trades — DB-persisted config for Strategy L1 (NIFTY RSI options).
======================================================================
Store JSON in `app_settings` under `light_l1_config`. Cache reads for 30s
to limit DB load when the strategy engine calls every tick.

Persisted keys (`light_l1_*`) are part of the public contract — documented in
`AGENTS.md`. Rename or reshape only together with the dashboard + engine.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from app_settings import get_bool, get_setting, set_bool, set_setting
from logger import get_logger

log = get_logger("light_strategy_config")

_CONFIG_KEY = "light_l1_config"
_TOGGLE_KEY = "light_l1_enabled"
_DAY_STATE_KEY = "light_l1_day_state"
# Named config snapshots (user profiles) — JSON object: { "MyAggro": { ... asdict ... }, ... }
_PROFILES_KEY = "light_l1_profiles"
_MAX_NAMED_PROFILES = 20

_CACHE_TTL_SEC = 30.0
_cached_cfg: dict[str, Any] | None = None
_cached_at: float = 0.0


@dataclass
class LightNiftyRSIConfig:
    rsi_period: int = 14
    rsi_buy_ce_below: float = 25.0
    rsi_buy_pe_above: float = 75.0
    rsi_exit_ce_above: float = 35.0
    rsi_exit_pe_below: float = 65.0
    min_premium: float = 30.0
    max_premium: float = 50.0
    otm_distance_min: float = 100.0
    otm_distance_max: float = 250.0
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 30.0
    time_stop_min: int = 90
    eod_squareoff_time: str = "15:15"
    max_trades_per_day: int = 2
    max_consecutive_losses: int = 2
    entry_window_start: str = "09:30"
    entry_window_end: str = "14:30"
    lot_size: int = 1
    mode: str = "PAPER"
    # Rule groups — when False, that filter/exit is skipped (defaults = current behaviour).
    use_entry_window: bool = True
    use_otm_distance_filter: bool = True
    use_premium_band: bool = True
    use_exit_eod: bool = True
    use_exit_time_stop: bool = True
    use_exit_profit_target: bool = True
    use_exit_stop_loss: bool = True
    use_exit_rsi: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LightNiftyRSIConfig:
        base = asdict(LightNiftyRSIConfig())
        for k in base:
            if k in d:
                base[k] = d[k]
        # Coerce types
        base["rsi_period"] = int(base["rsi_period"])
        base["time_stop_min"] = int(base["time_stop_min"])
        base["max_trades_per_day"] = int(base["max_trades_per_day"])
        base["max_consecutive_losses"] = int(base["max_consecutive_losses"])
        base["lot_size"] = int(base["lot_size"])
        for f in (
            "rsi_buy_ce_below",
            "rsi_buy_pe_above",
            "rsi_exit_ce_above",
            "rsi_exit_pe_below",
            "min_premium",
            "max_premium",
            "otm_distance_min",
            "otm_distance_max",
            "profit_target_pct",
            "stop_loss_pct",
        ):
            base[f] = float(base[f])
        base["mode"] = str(base["mode"]).upper()
        if base["mode"] not in ("PAPER", "LIVE"):
            base["mode"] = "PAPER"
        for b in (
            "use_entry_window",
            "use_otm_distance_filter",
            "use_premium_band",
            "use_exit_eod",
            "use_exit_time_stop",
            "use_exit_profit_target",
            "use_exit_stop_loss",
            "use_exit_rsi",
        ):
            v = base.get(b, True)
            if isinstance(v, bool):
                base[b] = v
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                base[b] = bool(v)
            elif isinstance(v, str):
                base[b] = v.strip().lower() in ("1", "true", "yes", "on")
            else:
                base[b] = bool(v)
        return cls(**base)


def default_config() -> LightNiftyRSIConfig:
    return LightNiftyRSIConfig()


def ensure_light_l1_schema(cfg: LightNiftyRSIConfig) -> LightNiftyRSIConfig:
    """
    Merge saved config onto current defaults so new fields (e.g. use_*) always exist.
    Use after loading older DB JSON or if the process briefly ran an older class definition.
    """
    merged = {**asdict(default_config()), **asdict(cfg)}
    return LightNiftyRSIConfig.from_dict(merged)


def load_config(force: bool = False) -> LightNiftyRSIConfig:
    """Load config from DB with process-local TTL cache."""
    global _cached_cfg, _cached_at
    now = time.monotonic()
    if not force and _cached_cfg is not None and (now - _cached_at) < _CACHE_TTL_SEC:
        cfg = LightNiftyRSIConfig.from_dict(_cached_cfg)
        return ensure_light_l1_schema(cfg)

    raw = get_setting(_CONFIG_KEY, "")
    if not raw.strip():
        cfg = default_config()
        _cached_cfg = asdict(cfg)
        _cached_at = now
        return cfg
    try:
        data = json.loads(raw)
        cfg = LightNiftyRSIConfig.from_dict(data if isinstance(data, dict) else {})
        cfg = ensure_light_l1_schema(cfg)
        _cached_cfg = asdict(cfg)
        _cached_at = now
        return cfg
    except Exception:
        log.error("load_config failed — using defaults", exc_info=True)
        cfg = default_config()
        _cached_cfg = asdict(cfg)
        _cached_at = now
        return cfg


def save_config(cfg: LightNiftyRSIConfig) -> None:
    """Persist config and invalidate cache."""
    global _cached_cfg, _cached_at
    set_setting(_CONFIG_KEY, cfg.to_json())
    _cached_cfg = asdict(cfg)
    _cached_at = time.monotonic()


def invalidate_cache() -> None:
    global _cached_cfg, _cached_at
    _cached_cfg = None
    _cached_at = 0.0


def is_light_l1_enabled() -> bool:
    return get_bool(_TOGGLE_KEY, False)


def set_light_l1_enabled(on: bool) -> None:
    set_bool(_TOGGLE_KEY, on)


@dataclass
class LightL1DayState:
    """Counters reset when `day` != today (handled in strategy)."""

    day: str
    trades_today: int = 0
    consecutive_losses: int = 0
    halted: bool = False


def load_day_state(today: str) -> LightL1DayState:
    raw = get_setting(_DAY_STATE_KEY, "")
    if not raw.strip():
        return LightL1DayState(day=today)
    try:
        d = json.loads(raw)
        if not isinstance(d, dict):
            return LightL1DayState(day=today)
        st = LightL1DayState(
            day=str(d.get("day", today)),
            trades_today=int(d.get("trades_today", 0)),
            consecutive_losses=int(d.get("consecutive_losses", 0)),
            halted=bool(d.get("halted", False)),
        )
        if st.day != today:
            return LightL1DayState(day=today)
        return st
    except Exception:
        log.error("load_day_state failed", exc_info=True)
        return LightL1DayState(day=today)


def save_day_state(state: LightL1DayState) -> None:
    set_setting(
        _DAY_STATE_KEY,
        json.dumps(
            {
                "day": state.day,
                "trades_today": state.trades_today,
                "consecutive_losses": state.consecutive_losses,
                "halted": state.halted,
            },
            ensure_ascii=False,
        ),
    )


def load_named_profiles() -> dict[str, dict[str, Any]]:
    """Return saved profile name → config dict. Max size enforced on save."""
    raw = get_setting(_PROFILES_KEY, "")
    if not raw.strip():
        return {}
    try:
        d = json.loads(raw)
        if not isinstance(d, dict):
            return {}
        return {str(k): v for k, v in d.items() if isinstance(v, dict)}
    except Exception:
        log.error("load_named_profiles failed", exc_info=True)
        return {}


def save_named_profile(name: str, cfg: LightNiftyRSIConfig) -> None:
    name = str(name).strip()
    if not name:
        raise ValueError("Profile name is required")
    prof = load_named_profiles()
    if name not in prof and len(prof) >= _MAX_NAMED_PROFILES:
        raise ValueError(f"At most {_MAX_NAMED_PROFILES} named profiles")
    prof[name] = asdict(cfg)
    set_setting(_PROFILES_KEY, json.dumps(prof, ensure_ascii=False))
    log.info(f"saved light L1 profile {name!r}")


def delete_named_profile(name: str) -> None:
    prof = load_named_profiles()
    prof.pop(str(name), None)
    set_setting(_PROFILES_KEY, json.dumps(prof, ensure_ascii=False) if prof else "{}")


def list_named_profile_names() -> list[str]:
    return sorted(load_named_profiles().keys())
