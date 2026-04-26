"""Unit tests — risk_manager.py approval gates."""

from __future__ import annotations

import sys
from datetime import datetime, time as dtime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from strategies.base_strategy import Signal
from risk_manager import RiskManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _signal(
    action:   str   = "BUY",
    symbol:   str   = "RELIANCE",
    strategy: str   = "RSI",
    price:    float = 100.0,
    qty:      int   = 10,
    meta:     dict  | None = None,
) -> Signal:
    return Signal(
        strategy = strategy,
        symbol   = symbol,
        exchange = "NSE",
        action   = action,
        quantity = qty,
        price    = price,
        reason   = "test signal",
        meta     = meta or {},
    )

def _rm(**kwargs) -> RiskManager:
    """Create a RiskManager with Telegram silenced."""
    with patch("risk_manager.send_risk_breach"):
        return RiskManager(**kwargs)

MARKET_OPEN  = dtime(9, 15)
MARKET_CLOSE = dtime(15, 25)
OUTSIDE_TIME = dtime(8, 0)   # before market


# ── Market hours ──────────────────────────────────────────────────────────────

def test_approve_blocks_outside_market_hours():
    """Signals during non-market hours should be rejected."""
    rm = _rm()
    rm._last_reset = datetime.now().strftime("%Y-%m-%d")   # prevent reset loop

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class _FakeNow:
                def time(self):      return dtime(8, 0)          # 8:00 AM — outside market
                def strftime(self, fmt): return datetime.now().strftime(fmt)
            return _FakeNow()

    rm_mod.datetime = FakeDT
    try:
        approved, reason = rm.approve(_signal())
        assert not approved
        assert "market hours" in reason.lower()
    finally:
        rm_mod.datetime = original


def test_approve_exit_always_passes():
    """EXIT signals bypass all checks including market hours."""
    rm = _rm()
    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(8, 0)   # outside market
                def strftime(self, fmt):
                    return "2024-01-15"
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        approved, reason = rm.approve(_signal(action="EXIT"))
        assert approved
        assert "EXIT" in reason
    finally:
        rm_mod.datetime = original


# ── Daily loss limit ──────────────────────────────────────────────────────────

def test_daily_loss_limit_blocks_new_signals():
    """After hitting max_daily_loss, all BUY/SELL signals are blocked."""
    rm = _rm(max_daily_loss=5000.0)
    rm._daily_pnl  = -5001.0   # already past the limit
    rm._last_reset = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class _FakeNow:
                def time(self):      return dtime(10, 30)         # inside market hours
                def strftime(self, fmt): return datetime.now().strftime(fmt)
            return _FakeNow()

    rm_mod.datetime = FakeDT
    try:
        with patch("risk_manager.send_risk_breach") as mock_alert:
            approved, reason = rm.approve(_signal())
        assert not approved
        assert "loss limit" in reason.lower()
        mock_alert.assert_called_once()
    finally:
        rm_mod.datetime = original


def test_daily_loss_limit_not_triggered_when_under():
    """P&L at -4999 (under limit) should not block."""
    rm = _rm(max_daily_loss=5000.0)
    rm._daily_pnl  = -4999.0
    rm._last_reset = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(10, 0)   # inside market
                def strftime(self, fmt):
                    return datetime.now().strftime(fmt)
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        approved, _ = rm.approve(_signal())
        assert approved
    finally:
        rm_mod.datetime = original


# ── Max positions ─────────────────────────────────────────────────────────────

def test_max_positions_blocks_new_symbol():
    """When max_positions is full, new symbols are rejected."""
    rm = _rm(max_positions=3)
    rm._open_positions = {"A", "B", "C"}   # full
    rm._last_reset     = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(10, 0)
                def strftime(self, fmt):
                    return datetime.now().strftime(fmt)
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        approved, reason = rm.approve(_signal(symbol="NEW"))
        assert not approved
        assert "position" in reason.lower()
    finally:
        rm_mod.datetime = original


def test_existing_symbol_not_blocked_by_position_limit():
    """Adding to an existing open position is always allowed (symbol already tracked)."""
    rm = _rm(max_positions=3)
    rm._open_positions = {"A", "B", "RELIANCE"}   # RELIANCE already open
    rm._last_reset     = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(10, 0)
                def strftime(self, fmt):
                    return datetime.now().strftime(fmt)
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        approved, _ = rm.approve(_signal(symbol="RELIANCE"))
        assert approved
    finally:
        rm_mod.datetime = original


# ── Max orders per day ────────────────────────────────────────────────────────

def test_max_orders_blocks_when_limit_reached():
    """When order count hits max_orders_day, reject."""
    rm = _rm(max_orders_day=5)
    rm._order_count = 5
    rm._last_reset  = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(10, 0)
                def strftime(self, fmt):
                    return datetime.now().strftime(fmt)
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        approved, reason = rm.approve(_signal())
        assert not approved
        assert "max orders" in reason.lower()
    finally:
        rm_mod.datetime = original


# ── Greeks (F&O) limits ───────────────────────────────────────────────────────

def test_greeks_delta_breach_blocks_signal():
    """Signal that would push net delta over max_delta is blocked."""
    rm = _rm(max_delta=500.0)
    rm._net_delta  = 450.0
    rm._last_reset = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(10, 0)
                def strftime(self, fmt):
                    return datetime.now().strftime(fmt)
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        sig = _signal(meta={"greeks": {"delta": 100, "theta": 0, "vega": 0}})
        approved, reason = rm.approve(sig)
        assert not approved
        assert "delta" in reason.lower()
    finally:
        rm_mod.datetime = original


def test_greeks_within_limits_passes():
    """Signal with Greeks well within limits is approved."""
    rm = _rm(max_delta=500.0, max_theta=-2000.0, max_vega=1000.0)
    rm._net_delta  = 0.0
    rm._last_reset = datetime.now().strftime("%Y-%m-%d")

    import risk_manager as rm_mod
    original = rm_mod.datetime

    class FakeDT:
        @staticmethod
        def now():
            class FakeNow:
                def time(self):
                    return dtime(10, 0)
                def strftime(self, fmt):
                    return datetime.now().strftime(fmt)
            return FakeNow()

    rm_mod.datetime = FakeDT
    try:
        sig = _signal(meta={"greeks": {"delta": 50, "theta": -100, "vega": 50}})
        approved, reason = rm.approve(sig)
        assert approved
    finally:
        rm_mod.datetime = original


# ── State updates ─────────────────────────────────────────────────────────────

def test_on_order_placed_tracks_positions():
    """on_order_placed() adds symbol to open positions."""
    rm = _rm()
    rm.on_order_placed(_signal(action="BUY", symbol="INFY"))
    assert "INFY" in rm._open_positions
    assert rm._order_count == 1


def test_on_order_placed_exit_removes_position():
    """EXIT signal removes symbol from open positions."""
    rm = _rm()
    rm._open_positions.add("RELIANCE")
    rm.on_order_placed(_signal(action="EXIT", symbol="RELIANCE"))
    assert "RELIANCE" not in rm._open_positions


def test_on_pnl_update_accumulates():
    """on_pnl_update() accumulates daily P&L correctly."""
    rm = _rm()
    rm.on_pnl_update(1500.0)
    rm.on_pnl_update(-2000.0)
    assert rm._daily_pnl == pytest.approx(-500.0)


def test_status_returns_expected_keys():
    """status() dict has all required keys."""
    rm = _rm()
    s = rm.status()
    for key in ("capital", "daily_pnl", "daily_pnl_%", "orders_today",
                "open_positions", "loss_limit_hit", "greeks"):
        assert key in s, f"Missing key: {key}"


def test_greeks_update_accumulates():
    """update_greeks() accumulates across calls."""
    rm = _rm()
    rm.update_greeks(delta=100, theta=-50, vega=30)
    rm.update_greeks(delta=50,  theta=-20, vega=10)
    status = rm.greeks_status()
    assert status["net_delta"] == pytest.approx(150.0)
    assert status["net_theta"] == pytest.approx(-70.0)
    assert status["net_vega"]  == pytest.approx(40.0)
