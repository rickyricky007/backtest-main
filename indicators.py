"""
Indicators Engine — Weighted Confluence Scoring System
=======================================================
10 powerful indicators, each returning a weighted score.

Scoring:
    +weight → BUY signal
    -weight → SELL signal
     0      → Neutral / not enough data

Total score range: -15 to +15
    score >= +6  → BUY  signal
    score <= -6  → SELL signal
    between      → NO TRADE

Indicators & Weights:
    #  Indicator          Weight  Type
    1  RSI(14)              2     Momentum — oversold/overbought
    2  MACD                 2     Trend + momentum crossover
    3  Bollinger Bands      2     Volatility breakout
    4  Supertrend           2     Trend direction
    5  EMA Crossover        2     Trend confirmation
    6  VWAP                 1     Intraday price anchor
    7  Volume Spike         1     Conviction confirmation
    8  ADX                  1     Trend strength filter
    9  Stochastic           1     Short-term reversal
    10 OI Change (F&O)      1     Smart money direction

Usage:
    from indicators import score_symbol, BUY_THRESHOLD, SELL_THRESHOLD

    result = score_symbol(
        closes=closes, highs=highs, lows=lows, volumes=volumes
    )
    if result["action"] == "BUY":
        # place trade
"""

from __future__ import annotations

from typing import Any
import numpy as np

from logger import get_logger

log = get_logger("indicators")

# ── Thresholds ────────────────────────────────────────────────────────────────
BUY_THRESHOLD  =  6   # score >= +6 → BUY
SELL_THRESHOLD = -6   # score <= -6 → SELL
MAX_SCORE      = 15   # 2+2+2+2+2+1+1+1+1+1


# ══════════════════════════════════════════════════════════════════════════════
# INDICATOR FUNCTIONS
# Each returns: +weight (BUY), -weight (SELL), or 0 (neutral)
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. RSI — Weight 2 ─────────────────────────────────────────────────────────

def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    result = np.zeros(len(values))
    result[0] = values[0]
    k = 2 / (period + 1)
    for i in range(1, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def check_rsi(closes: list[float], period: int = 14,
              oversold: float = 35, overbought: float = 65) -> int:
    """
    RSI(14) — Wilder's smoothing
    BUY  (+2): RSI < oversold  (35)
    SELL (-2): RSI > overbought (65)
    """
    try:
        if len(closes) < period + 2:
            return 0
        arr = np.array(closes, dtype=float)
        deltas = np.diff(arr)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rsi = 100 - (100 / (1 + avg_gain / avg_loss))

        if rsi < oversold:
            return +2
        if rsi > overbought:
            return -2
        return 0

    except Exception:
        log.error("RSI error", exc_info=True)
        return 0


# ── 2. MACD — Weight 2 ───────────────────────────────────────────────────────

def check_macd(closes: list[float],
               fast: int = 12, slow: int = 26, signal: int = 9) -> int:
    """
    MACD line crossover over signal line
    BUY  (+2): MACD crosses ABOVE signal line (bullish crossover)
    SELL (-2): MACD crosses BELOW signal line (bearish crossover)
    """
    try:
        if len(closes) < slow + signal + 2:
            return 0
        arr = np.array(closes, dtype=float)

        ema_fast   = _ema(arr, fast)
        ema_slow   = _ema(arr, slow)
        macd_line  = ema_fast - ema_slow
        signal_line = _ema(macd_line, signal)

        # Check crossover: previous vs current
        prev_diff = macd_line[-2] - signal_line[-2]
        curr_diff = macd_line[-1] - signal_line[-1]

        if prev_diff < 0 and curr_diff > 0:
            return +2   # bullish crossover
        if prev_diff > 0 and curr_diff < 0:
            return -2   # bearish crossover

        # Even without crossover — give half signal if strongly above/below
        if curr_diff > 0 and macd_line[-1] > 0:
            return +1
        if curr_diff < 0 and macd_line[-1] < 0:
            return -1

        return 0

    except Exception:
        log.error("MACD error", exc_info=True)
        return 0


# ── 3. Bollinger Bands — Weight 2 ────────────────────────────────────────────

def check_bollinger(closes: list[float], period: int = 20, std_dev: float = 2.0) -> int:
    """
    Bollinger Band touch / squeeze
    BUY  (+2): price touches or breaks BELOW lower band (oversold)
    SELL (-2): price touches or breaks ABOVE upper band (overbought)
    """
    try:
        if len(closes) < period:
            return 0
        arr    = np.array(closes[-period:], dtype=float)
        middle = np.mean(arr)
        std    = np.std(arr)
        upper  = middle + std_dev * std
        lower  = middle - std_dev * std
        price  = closes[-1]

        if price <= lower:
            return +2
        if price >= upper:
            return -2

        # Price approaching bands (within 10% of band distance)
        band_width = upper - lower
        if price <= lower + 0.1 * band_width:
            return +1
        if price >= upper - 0.1 * band_width:
            return -1

        return 0

    except Exception:
        log.error("Bollinger error", exc_info=True)
        return 0


# ── 4. Supertrend — Weight 2 ─────────────────────────────────────────────────

def check_supertrend(closes: list[float], highs: list[float], lows: list[float],
                     period: int = 10, multiplier: float = 3.0) -> int:
    """
    Supertrend indicator based on ATR
    BUY  (+2): price is ABOVE supertrend (uptrend)
    SELL (-2): price is BELOW supertrend (downtrend)
    """
    try:
        min_len = period + 5
        if len(closes) < min_len or len(highs) < min_len or len(lows) < min_len:
            return 0

        closes = np.array(closes, dtype=float)
        highs  = np.array(highs,  dtype=float)
        lows   = np.array(lows,   dtype=float)

        # ATR
        hl   = highs - lows
        hc   = np.abs(highs[1:] - closes[:-1])
        lc   = np.abs(lows[1:]  - closes[:-1])
        tr   = np.maximum(hl[1:], np.maximum(hc, lc))
        atr  = np.convolve(tr, np.ones(period) / period, mode='valid')

        if len(atr) < 2:
            return 0

        last_atr   = atr[-1]
        last_close = closes[-1]
        last_hl2   = (highs[-1] + lows[-1]) / 2

        upper = last_hl2 + multiplier * last_atr
        lower = last_hl2 - multiplier * last_atr

        # Simple determination: price vs bands
        if last_close > upper:
            return +2   # strong uptrend
        if last_close < lower:
            return -2   # strong downtrend
        # Price between bands — check direction vs midpoint
        if last_close > last_hl2:
            return +1
        if last_close < last_hl2:
            return -1

        return 0

    except Exception:
        log.error("Supertrend error", exc_info=True)
        return 0


# ── 5. EMA Crossover — Weight 2 ──────────────────────────────────────────────

def check_ema_crossover(closes: list[float], fast: int = 9, slow: int = 21) -> int:
    """
    EMA(9) vs EMA(21) crossover
    BUY  (+2): fast EMA crosses ABOVE slow EMA
    SELL (-2): fast EMA crosses BELOW slow EMA
    """
    try:
        if len(closes) < slow + 3:
            return 0
        arr  = np.array(closes, dtype=float)
        fast_ema = _ema(arr, fast)
        slow_ema = _ema(arr, slow)

        prev_diff = fast_ema[-2] - slow_ema[-2]
        curr_diff = fast_ema[-1] - slow_ema[-1]

        if prev_diff < 0 and curr_diff > 0:
            return +2   # golden cross
        if prev_diff > 0 and curr_diff < 0:
            return -2   # death cross

        # Trend confirmation (already above/below without crossover)
        if curr_diff > 0:
            return +1
        if curr_diff < 0:
            return -1

        return 0

    except Exception:
        log.error("EMA crossover error", exc_info=True)
        return 0


# ── 6. VWAP — Weight 1 ───────────────────────────────────────────────────────

def check_vwap(closes: list[float], highs: list[float],
               lows: list[float], volumes: list[float]) -> int:
    """
    VWAP (Volume Weighted Average Price)
    BUY  (+1): price ABOVE VWAP (bullish intraday bias)
    SELL (-1): price BELOW VWAP (bearish intraday bias)
    """
    try:
        if len(closes) < 2 or len(volumes) < 2:
            return 0

        closes  = np.array(closes,  dtype=float)
        highs   = np.array(highs,   dtype=float)
        lows    = np.array(lows,    dtype=float)
        volumes = np.array(volumes, dtype=float)

        typical_price = (highs + lows + closes) / 3
        total_vol = np.sum(volumes)

        if total_vol == 0:
            return 0

        vwap  = np.sum(typical_price * volumes) / total_vol
        price = closes[-1]

        if price > vwap * 1.002:   # 0.2% above VWAP → bullish
            return +1
        if price < vwap * 0.998:   # 0.2% below VWAP → bearish
            return -1
        return 0

    except Exception:
        log.error("VWAP error", exc_info=True)
        return 0


# ── 7. Volume Spike — Weight 1 ───────────────────────────────────────────────

def check_volume_spike(volumes: list[float], closes: list[float],
                       threshold: float = 1.5) -> int:
    """
    Volume spike with price direction
    BUY  (+1): volume spike + price going UP (bullish conviction)
    SELL (-1): volume spike + price going DOWN (bearish conviction)
    Neutral: spike without clear direction or no spike
    """
    try:
        if len(volumes) < 10 or len(closes) < 2:
            return 0

        avg_vol    = np.mean(volumes[-20:-1])   # avg of last 20 bars (excluding current)
        curr_vol   = volumes[-1]
        price_diff = closes[-1] - closes[-2]

        if avg_vol == 0:
            return 0

        if curr_vol >= avg_vol * threshold:
            if price_diff > 0:
                return +1   # volume spike + price up
            if price_diff < 0:
                return -1   # volume spike + price down

        return 0

    except Exception:
        log.error("Volume spike error", exc_info=True)
        return 0


# ── 8. ADX — Weight 1 ────────────────────────────────────────────────────────

def check_adx(closes: list[float], highs: list[float], lows: list[float],
              period: int = 14, threshold: float = 25.0) -> int:
    """
    ADX — Average Directional Index (trend strength filter)
    ADX > 25 means trend is strong enough to trade
    BUY  (+1): ADX > threshold AND +DI > -DI (bullish trend)
    SELL (-1): ADX > threshold AND -DI > +DI (bearish trend)
    Neutral  : ADX < threshold (ranging market — don't trade trend)
    """
    try:
        min_len = period * 2 + 2
        if len(closes) < min_len:
            return 0

        highs  = np.array(highs,  dtype=float)
        lows   = np.array(lows,   dtype=float)
        closes = np.array(closes, dtype=float)

        # True Range
        hl = highs[1:] - lows[1:]
        hc = np.abs(highs[1:] - closes[:-1])
        lc = np.abs(lows[1:]  - closes[:-1])
        tr = np.maximum(hl, np.maximum(hc, lc))

        # Directional Movement
        up_move   = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]

        plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # Smooth with Wilder's method
        def _wilder(arr, p):
            result = np.zeros(len(arr))
            result[p - 1] = np.sum(arr[:p])
            for i in range(p, len(arr)):
                result[i] = result[i - 1] - result[i - 1] / p + arr[i]
            return result

        atr14   = _wilder(tr, period)
        plus14  = _wilder(plus_dm, period)
        minus14 = _wilder(minus_dm, period)

        # +DI and -DI
        with np.errstate(divide='ignore', invalid='ignore'):
            plus_di  = np.where(atr14 > 0, 100 * plus14  / atr14, 0)
            minus_di = np.where(atr14 > 0, 100 * minus14 / atr14, 0)
            dx = np.where(
                (plus_di + minus_di) > 0,
                100 * np.abs(plus_di - minus_di) / (plus_di + minus_di),
                0
            )

        adx = _wilder(dx[period:], period)

        if len(adx) == 0:
            return 0

        last_adx      = adx[-1]
        last_plus_di  = plus_di[-1]
        last_minus_di = minus_di[-1]

        if last_adx > threshold:
            if last_plus_di > last_minus_di:
                return +1   # strong uptrend
            if last_minus_di > last_plus_di:
                return -1   # strong downtrend

        return 0   # ADX too low — ranging market

    except Exception:
        log.error("ADX error", exc_info=True)
        return 0


# ── 9. Stochastic — Weight 1 ─────────────────────────────────────────────────

def check_stochastic(closes: list[float], highs: list[float], lows: list[float],
                     k_period: int = 14, d_period: int = 3,
                     oversold: float = 20, overbought: float = 80) -> int:
    """
    Stochastic Oscillator %K and %D
    BUY  (+1): %K < oversold AND %K crosses above %D (reversal from bottom)
    SELL (-1): %K > overbought AND %K crosses below %D (reversal from top)
    """
    try:
        if len(closes) < k_period + d_period + 2:
            return 0

        closes = np.array(closes, dtype=float)
        highs  = np.array(highs,  dtype=float)
        lows   = np.array(lows,   dtype=float)

        k_values = []
        for i in range(k_period - 1, len(closes)):
            low_k  = np.min(lows[i - k_period + 1 : i + 1])
            high_k = np.max(highs[i - k_period + 1 : i + 1])
            if high_k == low_k:
                k_values.append(50.0)
            else:
                k_values.append(100 * (closes[i] - low_k) / (high_k - low_k))

        k_arr = np.array(k_values)
        if len(k_arr) < d_period + 1:
            return 0

        d_arr = np.convolve(k_arr, np.ones(d_period) / d_period, mode='valid')

        curr_k = k_arr[-1]
        prev_k = k_arr[-2]
        curr_d = d_arr[-1]
        prev_d = d_arr[-2]

        # BUY: oversold zone + K crosses above D
        if curr_k < oversold and prev_k < prev_d and curr_k > curr_d:
            return +1

        # SELL: overbought zone + K crosses below D
        if curr_k > overbought and prev_k > prev_d and curr_k < curr_d:
            return -1

        # Partial signal — just in zone
        if curr_k < oversold:
            return +1
        if curr_k > overbought:
            return -1

        return 0

    except Exception:
        log.error("Stochastic error", exc_info=True)
        return 0


# ── 10. OI Change (F&O only) — Weight 1 ──────────────────────────────────────

def check_oi_change(oi_current: float | None, oi_previous: float | None,
                    price_change_pct: float = 0.0) -> int:
    """
    Open Interest change — smart money direction (F&O only)

    Interpretation:
        OI up   + price up   → Long buildup  → BUY  (+1)
        OI up   + price down → Short buildup → SELL (-1)
        OI down + price up   → Short covering → mild BUY  (+1)
        OI down + price down → Long unwinding → mild SELL (-1)

    Pass None for non-F&O symbols → returns 0
    """
    try:
        if oi_current is None or oi_previous is None or oi_previous == 0:
            return 0

        oi_change_pct = (oi_current - oi_previous) / oi_previous * 100

        oi_rising  = oi_change_pct > 2.0    # OI up >2%
        oi_falling = oi_change_pct < -2.0   # OI down >2%
        price_up   = price_change_pct > 0.1
        price_down = price_change_pct < -0.1

        if oi_rising and price_up:
            return +1   # Long buildup — bullish
        if oi_rising and price_down:
            return -1   # Short buildup — bearish
        if oi_falling and price_up:
            return +1   # Short covering — bullish
        if oi_falling and price_down:
            return -1   # Long unwinding — bearish

        return 0

    except Exception:
        log.error("OI change error", exc_info=True)
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# MASTER SCORING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def score_symbol(
    closes:          list[float],
    highs:           list[float],
    lows:            list[float],
    volumes:         list[float],
    oi_current:      float | None = None,
    oi_previous:     float | None = None,
    price_change_pct: float       = 0.0,
) -> dict[str, Any]:
    """
    Run all 10 indicators and return a weighted confluence score.

    Returns dict:
    {
        "score":   int,          # -15 to +15
        "action":  str,          # "BUY", "SELL", or "WAIT"
        "signals": list[dict],   # breakdown per indicator
        "pct":     float,        # score as % of max (for UI display)
    }
    """

    signals: list[dict] = []

    def _add(name: str, score: int, weight: int) -> None:
        signals.append({
            "indicator": name,
            "score":     score,
            "weight":    weight,
            "signal":    "BUY" if score > 0 else ("SELL" if score < 0 else "—"),
        })

    # ── Run all 10 indicators ─────────────────────────────────────────────────
    s1  = check_rsi(closes)
    _add("RSI(14)", s1, 2)

    s2  = check_macd(closes)
    _add("MACD", s2, 2)

    s3  = check_bollinger(closes)
    _add("Bollinger Bands", s3, 2)

    s4  = check_supertrend(closes, highs, lows)
    _add("Supertrend", s4, 2)

    s5  = check_ema_crossover(closes)
    _add("EMA Crossover(9,21)", s5, 2)

    s6  = check_vwap(closes, highs, lows, volumes)
    _add("VWAP", s6, 1)

    s7  = check_volume_spike(volumes, closes)
    _add("Volume Spike", s7, 1)

    s8  = check_adx(closes, highs, lows)
    _add("ADX(14)", s8, 1)

    s9  = check_stochastic(closes, highs, lows)
    _add("Stochastic", s9, 1)

    s10 = check_oi_change(oi_current, oi_previous, price_change_pct)
    _add("OI Change", s10, 1)

    # ── Total score ───────────────────────────────────────────────────────────
    total = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8 + s9 + s10

    if total >= BUY_THRESHOLD:
        action = "BUY"
    elif total <= SELL_THRESHOLD:
        action = "SELL"
    else:
        action = "WAIT"

    pct = round(total / MAX_SCORE * 100, 1)

    return {
        "score":   total,
        "action":  action,
        "signals": signals,
        "pct":     pct,
        "buy_threshold":  BUY_THRESHOLD,
        "sell_threshold": SELL_THRESHOLD,
        "max_score":      MAX_SCORE,
    }


# ── Convenience: score summary string ────────────────────────────────────────

def score_summary(result: dict) -> str:
    """Human readable summary of scoring result."""
    score  = result["score"]
    action = result["action"]
    pct    = result["pct"]
    buy_signals  = sum(1 for s in result["signals"] if s["score"] > 0)
    sell_signals = sum(1 for s in result["signals"] if s["score"] < 0)
    return (
        f"{action} | Score: {score:+d}/{MAX_SCORE} ({pct:+.0f}%) | "
        f"BUY signals: {buy_signals} | SELL signals: {sell_signals}"
    )
