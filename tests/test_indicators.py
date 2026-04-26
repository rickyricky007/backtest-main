"""Unit tests — indicators.py scoring system."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from indicators import (
    check_rsi, check_macd, check_bollinger, check_ema_crossover,
    check_volume_spike, check_adx, check_stochastic,
    score_symbol, BUY_THRESHOLD, SELL_THRESHOLD, MAX_SCORE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flat(n: int = 100, price: float = 100.0) -> list[float]:
    return [price] * n

def _rising(n: int = 100, start: float = 80.0, end: float = 120.0) -> list[float]:
    step = (end - start) / n
    return [start + i * step for i in range(n)]

def _falling(n: int = 100, start: float = 120.0, end: float = 80.0) -> list[float]:
    step = (start - end) / n
    return [start - i * step for i in range(n)]

def _volumes(n: int = 100, base: float = 1000.0) -> list[float]:
    return [base] * n

def _spike_volumes(n: int = 100, base: float = 1000.0, spike: float = 3000.0) -> list[float]:
    v = [base] * n
    v[-1] = spike
    return v

def _oscillating(n: int = 100, base: float = 100.0, amp: float = 5.0) -> list[float]:
    """Prices that rise and fall equally → RSI ≈ 50 → neutral score."""
    import math
    return [base + amp * math.sin(2 * math.pi * i / 20) for i in range(n)]


# ── RSI tests ─────────────────────────────────────────────────────────────────

def test_rsi_buy_on_oversold():
    """Falling prices → RSI < 30 → should return positive score."""
    closes = _falling(100, 120, 70)
    result = check_rsi(closes)
    assert result > 0, f"Expected BUY score, got {result}"

def test_rsi_sell_on_overbought():
    """Rising prices → RSI > 70 → should return negative score."""
    closes = _rising(100, 70, 120)
    result = check_rsi(closes)
    assert result < 0, f"Expected SELL score, got {result}"

def test_rsi_neutral_on_oscillating():
    """Oscillating prices → RSI ≈ 50 → should return 0 (neither oversold nor overbought)."""
    closes = _oscillating(100, 100.0, 5.0)
    result = check_rsi(closes)
    assert result == 0, f"Expected neutral RSI score, got {result}"


# ── EMA crossover tests ───────────────────────────────────────────────────────

def test_ema_buy_on_rising():
    """Rising prices → fast EMA > slow EMA → BUY."""
    closes = _rising(100, 80, 120)
    result = check_ema_crossover(closes)
    assert result > 0

def test_ema_sell_on_falling():
    """Falling prices → fast EMA < slow EMA → SELL."""
    closes = _falling(100, 120, 80)
    result = check_ema_crossover(closes)
    assert result < 0


# ── Volume spike tests ────────────────────────────────────────────────────────

def test_volume_spike_detected():
    """Last candle volume 5x avg + price up → bullish spike → +1."""
    closes  = _rising(100, 90, 110)          # price going up
    volumes = _spike_volumes(100, 1000, 5000) # big volume on last candle
    result  = check_volume_spike(volumes, closes)
    assert result == 1, f"Expected +1 bullish spike, got {result}"

def test_volume_spike_bearish():
    """Last candle volume 5x avg + price down → bearish spike → -1."""
    closes  = _falling(100, 110, 90)          # price going down
    volumes = _spike_volumes(100, 1000, 5000)
    result  = check_volume_spike(volumes, closes)
    assert result == -1, f"Expected -1 bearish spike, got {result}"

def test_volume_normal_no_signal():
    """Flat volume → no spike → 0."""
    closes  = _flat(100, 100.0)
    volumes = _volumes(100, 1000)
    result  = check_volume_spike(volumes, closes)
    assert result == 0


# ── score_symbol tests ────────────────────────────────────────────────────────

def test_score_symbol_returns_correct_keys():
    closes  = _rising(100, 80, 120)
    highs   = [c + 2 for c in closes]
    lows    = [c - 2 for c in closes]
    volumes = _volumes(100)
    result  = score_symbol(closes, highs, lows, volumes)

    assert "score"   in result
    assert "action"  in result
    assert "pct"     in result
    assert "signals" in result

def test_score_within_range():
    closes  = _rising(100, 80, 120)
    highs   = [c + 2 for c in closes]
    lows    = [c - 2 for c in closes]
    volumes = _volumes(100)
    result  = score_symbol(closes, highs, lows, volumes)

    assert -MAX_SCORE <= result["score"] <= MAX_SCORE, f"Score {result['score']} out of range"

def test_uptrend_score_is_positive():
    """Rising prices → majority of trend indicators fire BUY → net score > 0."""
    closes  = _rising(100, 50, 150)
    highs   = [c + 1 for c in closes]
    lows    = [c - 1 for c in closes]
    volumes = _spike_volumes(100, 1000, 3000)
    result  = score_symbol(closes, highs, lows, volumes)

    assert result["score"] > 0, (
        f"Expected positive score for uptrend, got {result['score']}"
    )

def test_downtrend_score_is_negative():
    """Falling prices → majority of trend indicators fire SELL → net score < 0."""
    closes  = _falling(100, 150, 50)
    highs   = [c + 1 for c in closes]
    lows    = [c - 1 for c in closes]
    volumes = _spike_volumes(100, 1000, 3000)
    result  = score_symbol(closes, highs, lows, volumes)

    assert result["score"] < 0, (
        f"Expected negative score for downtrend, got {result['score']}"
    )

def test_rsi_buy_score_present_in_signals():
    """
    Falling prices → RSI fires BUY (+2) → it appears in score_symbol signals breakdown.
    Verifies the signals list correctly records individual indicator contributions.
    """
    closes  = _falling(100, 120, 60)
    highs   = [c + 0.5 for c in closes]
    lows    = [c - 0.5 for c in closes]
    volumes = _volumes(100)
    result  = score_symbol(closes, highs, lows, volumes)

    rsi_signal = next((s for s in result["signals"] if "RSI" in s["indicator"]), None)
    assert rsi_signal is not None
    assert rsi_signal["score"] == 2, (
        f"Expected RSI score +2 (oversold) in signals, got {rsi_signal['score']}"
    )

def test_thresholds_correct():
    """Verify BUY_THRESHOLD and SELL_THRESHOLD constants are set correctly."""
    assert BUY_THRESHOLD  ==  6, f"BUY_THRESHOLD should be 6, got {BUY_THRESHOLD}"
    assert SELL_THRESHOLD == -6, f"SELL_THRESHOLD should be -6, got {SELL_THRESHOLD}"
    assert MAX_SCORE      == 15, f"MAX_SCORE should be 15, got {MAX_SCORE}"

def test_insufficient_data_returns_neutral():
    """Less than 30 candles → should return WAIT, not crash."""
    closes  = [100.0] * 10
    highs   = [101.0] * 10
    lows    = [99.0]  * 10
    volumes = [1000.0]* 10
    result  = score_symbol(closes, highs, lows, volumes)
    assert result["action"] == "WAIT"
