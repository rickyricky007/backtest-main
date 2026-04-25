"""
Market Intelligence — Smart Money & Manipulation Detection
===========================================================
Detects institutional activity and market manipulation signals using:

1. OI Analysis
   - Long buildup  : OI ↑ + Price ↑  → bulls adding positions
   - Short buildup : OI ↑ + Price ↓  → bears adding positions
   - Long unwinding: OI ↓ + Price ↓  → bulls exiting (bearish)
   - Short covering: OI ↓ + Price ↑  → bears exiting (bullish)

2. Expiry Effects
   - Max pain analysis — price gravitates toward max pain on expiry
   - Expiry week behaviour — IV crush, last hour trap
   - Days to expiry alert

3. Manipulation Signals
   - Unusual volume spike (>3x average)
   - OI spike without price move (position building)
   - PCR extreme (>1.5 extreme greed, <0.5 extreme fear)
   - Gamma squeeze zone (price near heavy OI strike)

Usage:
    from market_intelligence import MarketIntelligence
    mi = MarketIntelligence(kite)
    report = mi.full_report("NIFTY 50")
"""

from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any

from logger import get_logger

log = get_logger("market_intelligence")

# ── Market hours (IST) ────────────────────────────────────────────────────────
MARKET_OPEN  = datetime.strptime("09:15", "%H:%M").time()
MARKET_CLOSE = datetime.strptime("15:30", "%H:%M").time()
PRE_MARKET   = datetime.strptime("09:00", "%H:%M").time()
LAST_HOUR    = datetime.strptime("14:30", "%H:%M").time()

# NSE monthly expiry: last Thursday of each month
# NSE weekly expiry:  every Thursday (NIFTY weekly)
WEEKLY_EXPIRY_DAY  = 3   # Thursday (weekday index)
MONTHLY_EXPIRY_DAY = 3   # Thursday


# ══════════════════════════════════════════════════════════════════════════════
# EXPIRY UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def days_to_expiry(expiry_date: date | str) -> int:
    """Returns calendar days remaining to expiry."""
    if isinstance(expiry_date, str):
        expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()
    return (expiry_date - date.today()).days


def next_weekly_expiry() -> date:
    """Returns the next NSE weekly expiry (Thursday)."""
    today = date.today()
    days_ahead = WEEKLY_EXPIRY_DAY - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def next_monthly_expiry() -> date:
    """Returns the last Thursday of current or next month."""
    today = date.today()
    # Find last Thursday of this month
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    last_day = next_month - timedelta(days=1)
    # Walk back to Thursday
    days_back = (last_day.weekday() - MONTHLY_EXPIRY_DAY) % 7
    last_thu  = last_day - timedelta(days=days_back)
    if last_thu < today:
        # Move to next month
        if next_month.month == 12:
            nn = next_month.replace(year=next_month.year + 1, month=1, day=1)
        else:
            nn = next_month.replace(month=next_month.month + 1, day=1)
        last_day  = nn - timedelta(days=1)
        days_back = (last_day.weekday() - MONTHLY_EXPIRY_DAY) % 7
        last_thu  = last_day - timedelta(days=days_back)
    return last_thu


def expiry_alert(expiry_date: date | None = None) -> dict:
    """
    Returns expiry status and alerts.
    """
    weekly  = next_weekly_expiry()
    monthly = next_monthly_expiry()
    dte_w   = days_to_expiry(weekly)
    dte_m   = days_to_expiry(monthly)

    alerts = []
    if dte_w == 0:
        alerts.append("⚠️ TODAY is weekly expiry — expect high volatility + IV crush after 3pm")
    elif dte_w == 1:
        alerts.append("📅 Weekly expiry TOMORROW — theta decay accelerates")
    elif dte_w <= 3:
        alerts.append(f"📅 Weekly expiry in {dte_w} days — consider theta strategies")

    if dte_m <= 5:
        alerts.append(f"📅 Monthly expiry in {dte_m} days — rollover activity expected")

    # Last hour trap
    now = datetime.now().time()
    if LAST_HOUR <= now <= MARKET_CLOSE:
        alerts.append("⏰ Last hour of trading — watch for reversal traps and sudden moves")

    return {
        "weekly_expiry":  weekly.strftime("%d %b %Y (%A)"),
        "monthly_expiry": monthly.strftime("%d %b %Y (%A)"),
        "dte_weekly":     dte_w,
        "dte_monthly":    dte_m,
        "alerts":         alerts,
        "is_expiry_day":  dte_w == 0,
        "is_expiry_week": dte_w <= 4,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MARKET SESSION
# ══════════════════════════════════════════════════════════════════════════════

def market_session_status() -> dict:
    """
    Returns current market session status for Indian + global markets.
    All times shown in IST.
    """
    now_ist = datetime.now()
    now_t   = now_ist.time()
    weekday = now_ist.weekday()   # 0=Mon, 6=Sun

    # Indian markets
    nse_open = (weekday < 5) and (MARKET_OPEN <= now_t <= MARKET_CLOSE)
    pre_open = (weekday < 5) and (PRE_MARKET <= now_t < MARKET_OPEN)

    # Global markets (approximate IST times)
    # SGX Nifty: 06:30–23:00 IST (important for Indian market gaps)
    sgx_open = (datetime.strptime("06:30", "%H:%M").time() <= now_t <=
                datetime.strptime("23:00", "%H:%M").time())

    # NYSE / NASDAQ: 19:00–01:30 IST (summer) / 20:00–02:30 IST (winter)
    nyse_open = (now_t >= datetime.strptime("19:00", "%H:%M").time() or
                 now_t <= datetime.strptime("01:30", "%H:%M").time())

    # London LSE: 13:30–22:00 IST
    lse_open = (datetime.strptime("13:30", "%H:%M").time() <= now_t <=
                datetime.strptime("22:00", "%H:%M").time())

    # Tokyo TSE: 05:30–11:30 IST
    tse_open = (datetime.strptime("05:30", "%H:%M").time() <= now_t <=
                datetime.strptime("11:30", "%H:%M").time())

    def _status(is_open: bool, name: str) -> dict:
        return {"market": name, "status": "🟢 OPEN" if is_open else "🔴 CLOSED", "open": is_open}

    sessions = [
        _status(pre_open or nse_open, "NSE/BSE India"),
        _status(sgx_open,             "SGX Nifty (Singapore)"),
        _status(lse_open,             "London LSE"),
        _status(nyse_open,            "NYSE/NASDAQ (US)"),
        _status(tse_open,             "Tokyo TSE"),
    ]

    phase = "CLOSED"
    if pre_open:
        phase = "PRE-OPEN (9:00–9:15)"
    elif nse_open and now_t < LAST_HOUR:
        phase = "MARKET OPEN"
    elif nse_open and now_t >= LAST_HOUR:
        phase = "LAST HOUR"

    return {
        "ist_time":    now_ist.strftime("%H:%M:%S IST | %d %b %Y (%A)"),
        "nse_phase":   phase,
        "nse_open":    nse_open,
        "sessions":    sessions,
        "is_weekend":  weekday >= 5,
    }


# ══════════════════════════════════════════════════════════════════════════════
# OI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyse_oi(
    oi_current:  float,
    oi_previous: float,
    price_current:  float,
    price_previous: float,
) -> dict:
    """
    Classify OI + price movement into smart money activity.
    """
    try:
        oi_change_pct    = (oi_current - oi_previous) / oi_previous * 100 if oi_previous else 0
        price_change_pct = (price_current - price_previous) / price_previous * 100 if price_previous else 0

        oi_up    = oi_change_pct > 1.0
        oi_down  = oi_change_pct < -1.0
        price_up = price_change_pct > 0.1
        price_down = price_change_pct < -0.1

        if oi_up and price_up:
            activity = "Long Buildup"
            bias     = "BULLISH"
            emoji    = "🟢"
            meaning  = "Institutions buying — fresh long positions being added"
        elif oi_up and price_down:
            activity = "Short Buildup"
            bias     = "BEARISH"
            emoji    = "🔴"
            meaning  = "Institutions selling — fresh short positions being added"
        elif oi_down and price_up:
            activity = "Short Covering"
            bias     = "BULLISH"
            emoji    = "🟡"
            meaning  = "Shorts exiting — potential reversal, not fresh buying"
        elif oi_down and price_down:
            activity = "Long Unwinding"
            bias     = "BEARISH"
            emoji    = "🟠"
            meaning  = "Longs exiting — distribution, potential fall ahead"
        else:
            activity = "Neutral"
            bias     = "NEUTRAL"
            emoji    = "⚪"
            meaning  = "No clear institutional activity"

        return {
            "activity":         activity,
            "bias":             bias,
            "emoji":            emoji,
            "meaning":          meaning,
            "oi_change_pct":    round(oi_change_pct, 2),
            "price_change_pct": round(price_change_pct, 2),
        }
    except Exception:
        log.error("OI analysis error", exc_info=True)
        return {"activity": "Error", "bias": "NEUTRAL", "emoji": "⚪", "meaning": "Could not analyse"}


# ══════════════════════════════════════════════════════════════════════════════
# MANIPULATION SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def detect_manipulation(
    volume_current:  float,
    volume_avg:      float,
    oi_change_pct:   float,
    price_change_pct: float,
    pcr:             float | None = None,
) -> list[dict]:
    """
    Detect potential market manipulation signals.
    Returns list of alerts — empty if nothing suspicious.
    """
    alerts = []

    try:
        # 1. Volume spike with no price move (quiet accumulation)
        if volume_avg > 0:
            vol_ratio = volume_current / volume_avg
            if vol_ratio >= 3.0 and abs(price_change_pct) < 0.3:
                alerts.append({
                    "type":    "QUIET ACCUMULATION",
                    "emoji":   "👀",
                    "detail":  f"Volume {vol_ratio:.1f}x average but price barely moved — someone quietly building position",
                    "severity": "HIGH",
                })
            elif vol_ratio >= 2.0:
                alerts.append({
                    "type":    "VOLUME SPIKE",
                    "emoji":   "📊",
                    "detail":  f"Volume {vol_ratio:.1f}x average — unusual activity",
                    "severity": "MEDIUM",
                })

        # 2. OI spike without price move (position building)
        if abs(oi_change_pct) >= 5.0 and abs(price_change_pct) < 0.2:
            alerts.append({
                "type":    "OI BUILDUP",
                "emoji":   "🏦",
                "detail":  f"OI changed {oi_change_pct:+.1f}% but price held — large positions being built quietly",
                "severity": "HIGH",
            })

        # 3. PCR extremes (put-call ratio)
        if pcr is not None:
            if pcr > 1.5:
                alerts.append({
                    "type":    "EXTREME FEAR (PCR HIGH)",
                    "emoji":   "😱",
                    "detail":  f"PCR = {pcr:.2f} — extreme bearish sentiment, often contrarian BUY signal",
                    "severity": "MEDIUM",
                })
            elif pcr < 0.5:
                alerts.append({
                    "type":    "EXTREME GREED (PCR LOW)",
                    "emoji":   "🤑",
                    "detail":  f"PCR = {pcr:.2f} — extreme bullish sentiment, often contrarian SELL signal",
                    "severity": "MEDIUM",
                })

        # 4. Expiry day manipulation check
        exp = expiry_alert()
        if exp["is_expiry_day"]:
            alerts.append({
                "type":    "EXPIRY DAY",
                "emoji":   "⚠️",
                "detail":  "Expiry day — max pain pulls, IV crush after 3pm, avoid holding OTM options",
                "severity": "HIGH",
            })

    except Exception:
        log.error("Manipulation detection error", exc_info=True)

    return alerts


# ══════════════════════════════════════════════════════════════════════════════
# MAX PAIN (from options chain data)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_max_pain(
    strikes:   list[float],
    call_oi:   list[float],
    put_oi:    list[float],
) -> dict:
    """
    Max Pain = strike at which total options buyer loss is maximum.
    At expiry, market tends to gravitate toward max pain.
    """
    try:
        if not strikes or len(strikes) != len(call_oi) != len(put_oi):
            return {"max_pain": None, "error": "Invalid data"}

        total_pain = []
        for test_price in strikes:
            call_loss = sum(max(0, test_price - k) * oi for k, oi in zip(strikes, call_oi))
            put_loss  = sum(max(0, k - test_price) * oi for k, oi in zip(strikes, put_oi))
            total_pain.append(call_loss + put_loss)

        max_pain_idx   = total_pain.index(min(total_pain))
        max_pain_price = strikes[max_pain_idx]

        return {
            "max_pain":   max_pain_price,
            "pain_values": list(zip(strikes, total_pain)),
            "error":      None,
        }
    except Exception:
        log.error("Max pain error", exc_info=True)
        return {"max_pain": None, "error": "Calculation failed"}


# ══════════════════════════════════════════════════════════════════════════════
# FULL INTELLIGENCE REPORT
# ══════════════════════════════════════════════════════════════════════════════

def full_report(
    symbol:           str,
    oi_current:       float | None = None,
    oi_previous:      float | None = None,
    price_current:    float | None = None,
    price_previous:   float | None = None,
    volume_current:   float | None = None,
    volume_avg:       float | None = None,
    pcr:              float | None = None,
) -> dict:
    """
    Generate a full intelligence report for a symbol.
    Returns all insights in one dict for dashboard display.
    """
    report: dict[str, Any] = {
        "symbol":    symbol,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }

    # Market session
    report["session"] = market_session_status()

    # Expiry info
    report["expiry"] = expiry_alert()

    # OI analysis
    if all(v is not None for v in [oi_current, oi_previous, price_current, price_previous]):
        report["oi"] = analyse_oi(oi_current, oi_previous, price_current, price_previous)
    else:
        report["oi"] = {"activity": "No OI data", "bias": "NEUTRAL", "emoji": "⚪", "meaning": "OI data not available"}

    # Manipulation signals
    manip_alerts = []
    if volume_current and volume_avg:
        oi_chg   = ((oi_current - oi_previous) / oi_previous * 100) if (oi_current and oi_previous) else 0
        price_chg = ((price_current - price_previous) / price_previous * 100) if (price_current and price_previous) else 0
        manip_alerts = detect_manipulation(volume_current, volume_avg, oi_chg, price_chg, pcr)

    report["manipulation_alerts"] = manip_alerts
    report["alert_count"]         = len(manip_alerts)

    return report
