"""
Strategy Engine
===============
The central brain — connects KiteTicker ticks to strategies to orders.

Usage:
    python strategy_engine.py

How it works:
    1. Connects to Kite WebSocket (KiteTicker)
    2. Subscribes to all symbols registered by active strategies
    3. On every tick → calls each matching strategy's on_tick()
    4. If a signal is returned → RiskManager checks it
    5. If approved → OrderManager executes it
    6. Logs everything

Adding a new strategy:
    1. Create strategies/my_strategy.py inheriting BaseStrategy
    2. Add it to ACTIVE_STRATEGIES below — that's it!
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

from kiteconnect import KiteTicker

import kite_data as kd
from logger import get_logger
from order_manager    import OrderManager
from risk_manager     import RiskManager
from stop_loss_manager import StopLossManager
from regime_filter    import RegimeTracker
from strategies       import RSIStrategy, SMAStrategy, LightNiftyRSIStrategy

log = get_logger("strategy_engine")

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURE YOUR STRATEGIES HERE
# Add, remove, or comment out strategies — engine picks them up automatically
# ═══════════════════════════════════════════════════════════════════════════════

ACTIVE_STRATEGIES = [

    RSIStrategy(
        symbol     = "RELIANCE",
        exchange   = "NSE",
        quantity   = 1,
        mode       = "PAPER",    # change to "LIVE" when ready
        period     = 14,
        oversold   = 30,
        overbought = 70,
    ),

    RSIStrategy(
        symbol     = "INFY",
        exchange   = "NSE",
        quantity   = 1,
        mode       = "PAPER",
        period     = 14,
        oversold   = 30,
        overbought = 70,
    ),

    SMAStrategy(
        symbol   = "HDFCBANK",
        exchange = "NSE",
        quantity = 1,
        mode     = "PAPER",
        fast     = 20,
        slow     = 50,
    ),

    # Light Trades L1 — gated by app_settings `light_l1_enabled` (see 4_Light_Strategies page)
    LightNiftyRSIStrategy(enabled=True),

    # ── Add more strategies here ────────────────────────────────────────────
    # SMAStrategy(symbol="TCS", quantity=1, mode="PAPER"),
    # RSIStrategy(symbol="SBIN", period=9, oversold=25, overbought=75, mode="PAPER"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# RISK CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

RISK = RiskManager(
    max_daily_loss  = 5_000,   # ₹ — stop trading if daily loss exceeds this
    max_positions   = 5,       # max simultaneous open positions
    max_orders_day  = 20,      # max total orders per day
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE — do not edit below unless you know what you're doing
# ═══════════════════════════════════════════════════════════════════════════════

ORDER_MGR  = OrderManager(mode="PAPER")   # overridden per-strategy based on signal.mode
SL_MGR     = StopLossManager(order_manager=ORDER_MGR)  # tracks SL & trailing SL for all positions
REGIME_MGR = RegimeTracker()              # tracks trending/ranging per symbol

# ── SL config per strategy (symbol → sl/target/trailing in ₹) ─────────────────
# Customize these per your risk appetite
SL_CONFIG: dict[str, dict] = {
    "RELIANCE": {"sl_points": 25.0,  "target_pts": 50.0,  "trailing_sl": 10.0},
    "INFY":     {"sl_points": 20.0,  "target_pts": 40.0,  "trailing_sl": 8.0},
    "HDFCBANK": {"sl_points": 30.0,  "target_pts": 60.0,  "trailing_sl": 12.0},
    # Add more symbols here as you add strategies
}

# Map instrument_token → list of strategies that care about it
_token_strategy_map: dict[int, list] = {}
_symbol_token_map:   dict[str, int]  = {}
_running = True


def _load_instrument_tokens() -> None:
    """Build symbol → instrument_token map from Kite instruments list."""
    log.info("Loading instrument tokens from Kite...")
    kite   = kd.kite_client()
    instrs = kite.instruments("NSE")
    for i in instrs:
        _symbol_token_map[i["tradingsymbol"]] = i["instrument_token"]
    log.info(f"Loaded {len(_symbol_token_map)} NSE instruments")


def _register_strategies() -> list[int]:
    """Map each strategy's symbol to its instrument token."""
    tokens = []
    for strategy in ACTIVE_STRATEGIES:
        if not strategy.enabled:
            log.info(f"⏭  Skipping disabled strategy: {strategy}")
            continue
        token = _symbol_token_map.get(strategy.symbol)
        if not token:
            log.warning(f"Token not found for {strategy.symbol} — skipping {strategy.name}")
            continue
        if token not in _token_strategy_map:
            _token_strategy_map[token] = []
        _token_strategy_map[token].append(strategy)
        tokens.append(token)
        log.info(f"✅ Registered: {strategy}")
    return list(set(tokens))


def on_ticks(ws, ticks):
    for tick in ticks:
        token      = tick.get("instrument_token")
        price      = tick.get("last_price", 0)
        strategies = _token_strategy_map.get(token, [])

        # ── Feed tick to Stop Loss Manager first ──────────────────────────────
        sl_exit = SL_MGR.on_tick(tick)
        if sl_exit:
            log.info(f"SL/Target triggered: {sl_exit}")

        # ── Update regime filter with OHLC if available ──────────────────────
        ohlc = tick.get("ohlc", {})
        if ohlc:
            REGIME_MGR.update(
                symbol = next((s.symbol for s in strategies), ""),
                high   = ohlc.get("high",  price),
                low    = ohlc.get("low",   price),
                close  = price,
                volume = tick.get("volume_traded", 0),
            )

        # ── Feed tick to each strategy ────────────────────────────────────────
        for strat in strategies:
            try:
                # ── Regime gate — block wrong strategy for current market ──────
                if not REGIME_MGR.allows(strat.symbol, strat.name):
                    regime = REGIME_MGR.regime(strat.symbol)
                    adx    = REGIME_MGR.adx(strat.symbol)
                    # Log once per minute to avoid spam (use a simple counter trick)
                    if not hasattr(strat, "_regime_block_count"):
                        strat._regime_block_count = 0
                    strat._regime_block_count += 1
                    if strat._regime_block_count % 100 == 1:
                        log.info(f"Regime block: {strat.name} on {strat.symbol} — market is {regime} (ADX={adx:.1f})")
                    continue
                else:
                    strat._regime_block_count = 0

                sig = strat.on_tick(tick)
                if sig is None:
                    continue

                # ── Risk check ────────────────────────────────────────────────
                approved, reason = RISK.approve(sig)
                if not approved:
                    log.warning(f"Risk blocked: {sig.strategy} {sig.action} {sig.symbol} — {reason}")
                    continue

                # ── Execute order ─────────────────────────────────────────────
                mgr    = OrderManager(mode=strat.mode)
                result = mgr.execute(sig)

                if "success" in result:
                    RISK.on_order_placed(sig)
                    _send_alert(sig)

                    # ── Register position with SL Manager ─────────────────────
                    if (
                        sig.action in ("BUY", "SELL")
                        and not getattr(strat, "manages_own_exits", False)
                    ):
                        sl_cfg = SL_CONFIG.get(sig.symbol, {
                            "sl_points":  20.0,
                            "target_pts": 40.0,
                            "trailing_sl": 0.0,
                        })
                        SL_MGR.register(
                            symbol      = sig.symbol,
                            action      = sig.action,
                            entry_price = sig.price,
                            qty         = sig.quantity,
                            exchange    = sig.exchange,
                            strategy    = sig.strategy,
                            **sl_cfg,
                        )
                else:
                    log.error(f"Order failed: {result.get('error')}")

            except Exception as e:
                log.error(f"Error in {strat.name}: {e}", exc_info=True)


def _send_alert(sig) -> None:
    """Send Telegram alert for executed signals (non-blocking, gated on 'signal' toggle)."""
    try:
        from alert_engine import send_telegram_message
        from config import cfg
        token   = cfg.telegram_bot_token
        chat_id = cfg.telegram_chat_id
        if token and chat_id:
            emoji = "🟢" if sig.action == "BUY" else "🔴" if sig.action == "SELL" else "🟡"
            msg = (
                f"{emoji} <b>{sig.strategy} — {sig.action}</b>\n\n"
                f"📌 Symbol: <b>{sig.symbol}</b>\n"
                f"💰 Price: ₹{sig.price:,.2f}\n"
                f"📊 Qty: {sig.quantity}\n"
                f"📝 Reason: {sig.reason}\n"
                f"⚙️ Mode: {sig.strategy}\n"
                f"⏰ {sig.timestamp.strftime('%d %b %Y %H:%M:%S')}"
            )
            # Gated through alert_engine.send_telegram_message → master+per-alert
            send_telegram_message(token, chat_id, msg, alert_id="signal")
    except Exception:
        log.warning("_send_alert failed (non-critical)", exc_info=True)


def on_connect(ws, response):
    tokens = list(_token_strategy_map.keys())
    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_FULL, tokens)
    symbols = [s for strat_list in _token_strategy_map.values()
               for s in [strat_list[0].symbol]]
    log.info(f"🚀 Connected — watching: {', '.join(symbols)}")


def on_reconnect(ws, attempts):
    log.warning(f"🔄 Reconnecting... attempt {attempts}")


def on_noreconnect(ws):
    log.error("Max reconnects reached. Restart the engine.")


def on_error(ws, code, reason):
    log.warning(f"WebSocket error {code}: {reason}")


def on_close(ws, code, reason):
    log.warning(f"WebSocket closed: {code} — {reason}")


def _handle_signal(sig, frame):
    global _running
    log.info("Shutting down gracefully...")
    for strat in ACTIVE_STRATEGIES:
        strat.on_stop()
    _running = False
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("=" * 60)
    log.info("  STRATEGY ENGINE")
    log.info("=" * 60)
    log.info(f"  Strategies : {len(ACTIVE_STRATEGIES)}")
    log.info(f"  Risk limit : ₹{RISK.max_daily_loss:,.0f}/day")
    log.info(f"  Max orders : {RISK.max_orders_day}/day")
    log.info("=" * 60)

    # Load tokens
    _load_instrument_tokens()

    # Register strategies
    tokens = _register_strategies()
    if not tokens:
        log.error("No strategies registered. Add strategies to ACTIVE_STRATEGIES.")
        sys.exit(1)

    # Call on_start for each strategy
    for strat in ACTIVE_STRATEGIES:
        if strat.enabled:
            strat.on_start()

    # Connect KiteTicker
    kite = kd.kite_client()
    kws  = KiteTicker(kite.api_key, kite.access_token)

    kws.on_ticks       = on_ticks
    kws.on_connect     = on_connect
    kws.on_reconnect   = on_reconnect
    kws.on_noreconnect = on_noreconnect
    kws.on_error       = on_error
    kws.on_close       = on_close

    log.info("Connecting to Kite WebSocket...")
    kws.connect(threaded=False)


if __name__ == "__main__":
    main()
