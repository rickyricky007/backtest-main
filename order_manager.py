"""
Order Manager — Phase 1 Complete
=================================
Supports all Kite order types in both PAPER and LIVE mode.

Order types:
    market()   — execute immediately at market price
    limit()    — execute at a specific price or better
    sl()       — stop-loss limit (triggers at SL price, fills at limit)
    sl_market()— stop-loss market (triggers at SL price, fills at market)
    bracket()  — entry + automatic target + stop-loss in one order
    cover()    — entry + mandatory stop-loss in one order

Order management:
    modify()   — change price / qty / trigger price of a pending order
    cancel()   — cancel a pending order
    status()   — get live status of any order from Kite
    history()  — full audit trail of an order

All orders logged to dashboard.sqlite → engine_orders table.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from db import execute, query, init_tables
from logger import get_logger

log = get_logger("order_manager")

if TYPE_CHECKING:
    from strategies.base_strategy import Signal


# ── DB helpers ────────────────────────────────────────────────────────────────

def _log(
    symbol: str, action: str, order_type: str, variety: str,
    product: str, quantity: int, price: float, trigger_price: float,
    mode: str, status: str, order_id: str = "",
    strategy: str = "", exchange: str = "NSE",
    sq_off: float = 0, stoploss: float = 0, trailing_sl: float = 0,
    reason: str = "", meta: dict | None = None,
    parent_order_id: str = "",
) -> None:
    """Insert an order record into Supabase."""
    execute("""
        INSERT INTO engine_orders (
            timestamp, strategy, symbol, exchange, action, order_type,
            variety, product, quantity, price, trigger_price, sq_off,
            stoploss, trailing_sl, mode, order_id,
            status, notes
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        strategy, symbol, exchange, action, order_type,
        variety, product, quantity, price, trigger_price, sq_off,
        stoploss, trailing_sl, mode, order_id,
        status, json.dumps(meta or {}),
    ))


def _update_status(order_id: str, status: str) -> None:
    """Update status of an existing order by Kite order_id."""
    execute(
        "UPDATE engine_orders SET status=%s WHERE order_id=%s",
        (status, order_id)
    )


# ── Order Manager ─────────────────────────────────────────────────────────────

class OrderManager:
    """
    Central order manager — use this everywhere in your codebase.

    Quick usage:
        om = OrderManager(mode="PAPER")  # or "LIVE"

        # From a strategy signal
        om.execute(signal)

        # Direct order placement
        om.market("RELIANCE", "BUY", qty=10)
        om.limit("INFY", "BUY", qty=5, price=1500.0)
        om.bracket("NIFTY24DEC23000CE", "BUY", qty=50,
                   price=150.0, sq_off=20.0, stoploss=10.0)
        om.sl("HDFCBANK", "SELL", qty=10,
              price=1490.0, trigger_price=1495.0)

        # Manage orders
        om.modify(order_id="123456", price=1510.0)
        om.cancel(order_id="123456")
        om.status(order_id="123456")
    """

    def __init__(self, mode: str = "PAPER", product: str = "MIS"):
        """
        mode    : "PAPER" or "LIVE"
        product : "MIS" (intraday), "CNC" (delivery), "NRML" (F&O)
        """
        self.mode    = mode.upper()
        self.product = product.upper()
        init_tables()
        log.info(f"OrderManager {self.mode} mode | product={self.product}")

    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC ORDER PLACEMENT METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    def execute(self, signal: "Signal") -> dict:
        """
        Place a MARKET order from a strategy Signal object.
        This is the main entry point called by the strategy engine.
        """
        return self.market(
            symbol   = signal.symbol,
            action   = signal.action,
            qty      = signal.quantity,
            exchange = signal.exchange,
            strategy = signal.strategy,
            reason   = signal.reason,
            meta     = signal.meta,
        )

    def market(
        self,
        symbol:   str,
        action:   str,
        qty:      int,
        exchange: str  = "NSE",
        strategy: str  = "",
        reason:   str  = "",
        meta:     dict | None = None,
    ) -> dict:
        """Market order — fills immediately at best available price."""
        return self._place(
            symbol=symbol, action=action, qty=qty,
            order_type="MARKET", variety="REGULAR",
            exchange=exchange, price=0, trigger_price=0,
            strategy=strategy, reason=reason, meta=meta,
        )

    def limit(
        self,
        symbol:   str,
        action:   str,
        qty:      int,
        price:    float,
        exchange: str  = "NSE",
        strategy: str  = "",
        reason:   str  = "",
        meta:     dict | None = None,
    ) -> dict:
        """
        Limit order — fills only at `price` or better.
        Use when you want a specific entry/exit price.
        """
        return self._place(
            symbol=symbol, action=action, qty=qty,
            order_type="LIMIT", variety="REGULAR",
            exchange=exchange, price=price, trigger_price=0,
            strategy=strategy, reason=reason, meta=meta,
        )

    def sl(
        self,
        symbol:        str,
        action:        str,
        qty:           int,
        price:         float,
        trigger_price: float,
        exchange:      str  = "NSE",
        strategy:      str  = "",
        reason:        str  = "",
        meta:          dict | None = None,
    ) -> dict:
        """
        Stop-Loss Limit order.
        Triggers when price hits `trigger_price`,
        then places a limit order at `price`.

        Example: SL SELL with trigger=495, price=490
        → activates when price drops to 495, sells at 490 or better.
        """
        return self._place(
            symbol=symbol, action=action, qty=qty,
            order_type="SL", variety="REGULAR",
            exchange=exchange, price=price,
            trigger_price=trigger_price,
            strategy=strategy, reason=reason, meta=meta,
        )

    def sl_market(
        self,
        symbol:        str,
        action:        str,
        qty:           int,
        trigger_price: float,
        exchange:      str  = "NSE",
        strategy:      str  = "",
        reason:        str  = "",
        meta:          dict | None = None,
    ) -> dict:
        """
        Stop-Loss Market order.
        Triggers when price hits `trigger_price`,
        then fills immediately at market price.
        Faster execution than SL-Limit but less price control.
        """
        return self._place(
            symbol=symbol, action=action, qty=qty,
            order_type="SL-M", variety="REGULAR",
            exchange=exchange, price=0,
            trigger_price=trigger_price,
            strategy=strategy, reason=reason, meta=meta,
        )

    def bracket(
        self,
        symbol:      str,
        action:      str,
        qty:         int,
        price:       float,
        sq_off:      float,
        stoploss:    float,
        trailing_sl: float = 0,
        exchange:    str   = "NSE",
        strategy:    str   = "",
        reason:      str   = "",
        meta:        dict | None = None,
    ) -> dict:
        """
        Bracket Order — entry + auto target + auto stop-loss in one shot.

        sq_off      : target points AWAY from entry (profit booking)
        stoploss    : stop-loss points AWAY from entry (loss protection)
        trailing_sl : trailing stop-loss points (0 = disabled)

        Example: BUY RELIANCE @ 2500, sq_off=50, stoploss=25
        → target = 2550, stop-loss = 2475 (placed automatically)
        """
        return self._place(
            symbol=symbol, action=action, qty=qty,
            order_type="LIMIT", variety="BO",
            exchange=exchange, price=price, trigger_price=0,
            sq_off=sq_off, stoploss=stoploss, trailing_sl=trailing_sl,
            strategy=strategy, reason=reason, meta=meta,
        )

    def cover(
        self,
        symbol:        str,
        action:        str,
        qty:           int,
        price:         float,
        trigger_price: float,
        exchange:      str  = "NSE",
        strategy:      str  = "",
        reason:        str  = "",
        meta:          dict | None = None,
    ) -> dict:
        """
        Cover Order — market/limit entry with a mandatory stop-loss.
        Lower margin requirement than regular orders.

        trigger_price : stop-loss trigger level
        """
        return self._place(
            symbol=symbol, action=action, qty=qty,
            order_type="MARKET", variety="CO",
            exchange=exchange, price=price,
            trigger_price=trigger_price,
            strategy=strategy, reason=reason, meta=meta,
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # ORDER MANAGEMENT — modify, cancel, status, history
    # ═══════════════════════════════════════════════════════════════════════════

    def modify(
        self,
        order_id:      str,
        qty:           int   | None = None,
        price:         float | None = None,
        trigger_price: float | None = None,
        order_type:    str   | None = None,
    ) -> dict:
        """
        Modify a pending order on Kite.
        Only works for OPEN/PENDING orders — cannot modify filled orders.

        Pass only the fields you want to change.
        """
        if self.mode == "PAPER":
            log.info(f"Paper modify order {order_id}")
            return {"success": True, "order_id": order_id, "mode": "PAPER", "action": "MODIFIED"}

        try:
            import kite_data as kd
            kite   = kd.kite_client()
            kwargs: dict[str, Any] = {"order_id": order_id, "variety": "regular"}
            if qty           is not None: kwargs["quantity"]      = qty
            if price         is not None: kwargs["price"]         = price
            if trigger_price is not None: kwargs["trigger_price"] = trigger_price
            if order_type    is not None: kwargs["order_type"]    = order_type

            result = kite.modify_order(**kwargs)
            _update_status(order_id, "MODIFIED")
            log.info(f"✅ Modified order {order_id}")
            return {"success": True, "order_id": result}
        except Exception as e:
            log.error(f"Modify order failed: {e}", exc_info=True)
            return {"error": str(e)}

    def cancel(self, order_id: str, variety: str = "regular") -> dict:
        """
        Cancel a pending order on Kite.
        Cannot cancel already filled or rejected orders.
        """
        if self.mode == "PAPER":
            _update_status(order_id, "CANCELLED")
            log.info(f"Paper cancel order {order_id}")
            return {"success": True, "order_id": order_id, "mode": "PAPER", "action": "CANCELLED"}

        try:
            import kite_data as kd
            kite   = kd.kite_client()
            result = kite.cancel_order(variety=variety, order_id=order_id)
            _update_status(order_id, "CANCELLED")
            log.info(f"✅ Cancelled order {order_id}")
            return {"success": True, "order_id": result}
        except Exception as e:
            log.error(f"Cancel order failed: {e}", exc_info=True)
            return {"error": str(e)}

    def status(self, order_id: str) -> dict:
        """
        Get live status of a specific order from Kite.
        Returns full order details including fill price and qty.
        """
        if self.mode == "PAPER":
            rows = query(
                "SELECT * FROM engine_orders WHERE order_id=%s ORDER BY id DESC LIMIT 1",
                (order_id,)
            )
            return rows[0] if rows else {"error": "Order not found"}

        try:
            import kite_data as kd
            kite   = kd.kite_client()
            orders = kite.orders()
            for o in orders:
                if str(o.get("order_id")) == str(order_id):
                    _update_status(order_id, o.get("status", "UNKNOWN"))
                    return o
            return {"error": f"Order {order_id} not found on Kite"}
        except Exception as e:
            return {"error": str(e)}

    def history(self, order_id: str) -> list[dict]:
        """
        Get full audit trail of an order from Kite.
        Shows every state change (OPEN → COMPLETE, etc.).
        """
        if self.mode == "PAPER":
            return [self.status(order_id)]

        try:
            import kite_data as kd
            kite = kd.kite_client()
            return kite.order_trades(order_id)
        except Exception as e:
            return [{"error": str(e)}]

    def open_orders(self) -> list[dict]:
        """Get all currently open/pending orders from Kite."""
        if self.mode == "PAPER":
            return query(
                "SELECT * FROM engine_orders WHERE status IN ('PLACED','OPEN','PENDING') ORDER BY id DESC"
            )

        try:
            import kite_data as kd
            return kd.kite_client().orders()
        except Exception as e:
            return [{"error": str(e)}]

    def positions(self) -> dict:
        """Get current open positions from Kite."""
        if self.mode == "PAPER":
            return {"message": "Use paper portfolio for paper positions"}

        try:
            import kite_data as kd
            return kd.kite_client().positions()
        except Exception as e:
            return {"error": str(e)}

    def cancel_all_open(self) -> list[dict]:
        """Emergency: cancel ALL open orders. Use carefully."""
        results = []
        for order in self.open_orders():
            oid = order.get("order_id") or order.get("id", "")
            if oid:
                results.append(self.cancel(str(oid)))
        log.warning(f"Cancelled {len(results)} open orders (cancel_all_open)")
        return results

    # ── Order history from DB ─────────────────────────────────────────────────

    def get_orders(self, limit: int = 100, symbol: str = "") -> list[dict]:
        """Fetch recent orders from Supabase."""
        if symbol:
            return query(
                "SELECT * FROM engine_orders WHERE symbol=%s ORDER BY id DESC LIMIT %s",
                (symbol.upper(), limit)
            )
        return query(
            "SELECT * FROM engine_orders ORDER BY id DESC LIMIT %s",
            (limit,)
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # INTERNAL — core placement logic
    # ═══════════════════════════════════════════════════════════════════════════

    def _place(
        self,
        symbol:        str,
        action:        str,
        qty:           int,
        order_type:    str,
        variety:       str,
        exchange:      str   = "NSE",
        price:         float = 0,
        trigger_price: float = 0,
        sq_off:        float = 0,
        stoploss:      float = 0,
        trailing_sl:   float = 0,
        strategy:      str   = "",
        reason:        str   = "",
        meta:          dict | None = None,
    ) -> dict:
        label = f"{variety} {order_type} {action} {qty} {symbol}"
        log.info(f"→ {label} @ ₹{price or 'MARKET'}")

        if self.mode == "PAPER":
            return self._paper_place(
                symbol=symbol, action=action, qty=qty,
                order_type=order_type, variety=variety,
                exchange=exchange, price=price,
                trigger_price=trigger_price, sq_off=sq_off,
                stoploss=stoploss, trailing_sl=trailing_sl,
                strategy=strategy, reason=reason, meta=meta,
            )
        return self._live_place(
            symbol=symbol, action=action, qty=qty,
            order_type=order_type, variety=variety,
            exchange=exchange, price=price,
            trigger_price=trigger_price, sq_off=sq_off,
            stoploss=stoploss, trailing_sl=trailing_sl,
            strategy=strategy, reason=reason, meta=meta,
        )

    def _paper_place(self, **kw) -> dict:
        order_id   = f"PAPER_{kw['symbol']}_{int(time.time())}"
        raw_price  = kw["price"] or 0.0

        # ── Slippage model ────────────────────────────────────────────────────
        # Real markets never fill at the exact signal price.
        # We model slippage based on exchange and order type.
        #   NSE equities  : 0.05% slippage (liquid stocks, tight spreads)
        #   NFO options   : 0.15% slippage (wider spreads, less liquidity)
        #   NFO futures   : 0.05% slippage (very liquid)
        #   Market orders : full slippage applied
        #   Limit orders  : half slippage (partial fill at worse price)
        exchange   = kw.get("exchange", "NSE").upper()
        order_type = kw.get("order_type", "MARKET").upper()
        action     = kw.get("action", "BUY").upper()

        if exchange == "NFO" and ("CE" in kw["symbol"] or "PE" in kw["symbol"]):
            slip_pct = 0.0015   # 0.15% for options
        elif exchange == "NFO":
            slip_pct = 0.0005   # 0.05% for futures
        else:
            slip_pct = 0.0005   # 0.05% for NSE equity

        if order_type in ("LIMIT", "SL"):
            slip_pct /= 2       # limit orders get half slippage

        # Slippage goes against you: BUY fills higher, SELL fills lower
        if raw_price > 0:
            if action in ("BUY", "EXIT_SHORT"):
                fill_price = round(raw_price * (1 + slip_pct), 2)
            else:
                fill_price = round(raw_price * (1 - slip_pct), 2)
            slip_amt = abs(fill_price - raw_price)
        else:
            fill_price = 0.0   # true market order — no signal price
            slip_amt   = 0.0

        _log(
            symbol=kw["symbol"], action=action,
            order_type=order_type, variety=kw["variety"],
            product=self.product, quantity=kw["qty"],
            price=fill_price, trigger_price=kw["trigger_price"],
            mode="PAPER", status="FILLED", order_id=order_id,
            strategy=kw.get("strategy", ""),
            exchange=exchange,
            sq_off=kw.get("sq_off", 0),
            stoploss=kw.get("stoploss", 0),
            trailing_sl=kw.get("trailing_sl", 0),
            reason=kw.get("reason", ""),
            meta={**(kw.get("meta") or {}),
                  "signal_price": raw_price,
                  "fill_price":   fill_price,
                  "slippage_amt": slip_amt,
                  "slippage_pct": round(slip_pct * 100, 4)},
        )
        log.info(f"✅ Paper filled: {order_id} @ ₹{fill_price:.2f} (signal ₹{raw_price:.2f}, slip ₹{slip_amt:.2f})")
        return {
            "success":      True,
            "order_id":     order_id,
            "mode":         "PAPER",
            "status":       "FILLED",
            "fill_price":   fill_price,
            "signal_price": raw_price,
            "slippage_amt": slip_amt,
            "slippage_pct": round(slip_pct * 100, 4),
        }

    def _live_place(self, **kw) -> dict:
        try:
            import kite_data as kd
            kite = kd.kite_client()

            # Map action → Kite transaction type
            is_buy = kw["action"].upper() in ("BUY", "EXIT_SHORT")
            txn    = kite.TRANSACTION_TYPE_BUY if is_buy else kite.TRANSACTION_TYPE_SELL

            # Map variety
            variety_map = {
                "REGULAR": kite.VARIETY_REGULAR,
                "BO":      kite.VARIETY_BO,
                "CO":      kite.VARIETY_CO,
            }
            kite_variety = variety_map.get(kw["variety"].upper(), kite.VARIETY_REGULAR)

            # Map order type
            order_type_map = {
                "MARKET": kite.ORDER_TYPE_MARKET,
                "LIMIT":  kite.ORDER_TYPE_LIMIT,
                "SL":     kite.ORDER_TYPE_SL,
                "SL-M":   kite.ORDER_TYPE_SLM,
            }
            kite_order_type = order_type_map.get(kw["order_type"].upper(), kite.ORDER_TYPE_MARKET)

            # Map product
            product_map = {
                "MIS":  kite.PRODUCT_MIS,
                "CNC":  kite.PRODUCT_CNC,
                "NRML": kite.PRODUCT_NRML,
            }
            kite_product = product_map.get(self.product, kite.PRODUCT_MIS)

            # Build kwargs
            place_kwargs: dict[str, Any] = dict(
                variety          = kite_variety,
                exchange         = kw.get("exchange", "NSE"),
                tradingsymbol    = kw["symbol"],
                transaction_type = txn,
                quantity         = kw["qty"],
                order_type       = kite_order_type,
                product          = kite_product,
            )

            if kw["price"]         and kw["price"] > 0:         place_kwargs["price"]          = kw["price"]
            if kw["trigger_price"] and kw["trigger_price"] > 0: place_kwargs["trigger_price"]  = kw["trigger_price"]
            if kw.get("sq_off")    and kw["sq_off"] > 0:        place_kwargs["squareoff"]      = kw["sq_off"]
            if kw.get("stoploss")  and kw["stoploss"] > 0:      place_kwargs["stoploss"]       = kw["stoploss"]
            if kw.get("trailing_sl") and kw["trailing_sl"] > 0: place_kwargs["trailing_stoploss"] = kw["trailing_sl"]

            order_id = kite.place_order(**place_kwargs)

            _log(
                symbol=kw["symbol"], action=kw["action"],
                order_type=kw["order_type"], variety=kw["variety"],
                product=self.product, quantity=kw["qty"],
                price=kw["price"], trigger_price=kw["trigger_price"],
                mode="LIVE", status="PLACED", order_id=str(order_id),
                strategy=kw.get("strategy", ""),
                exchange=kw.get("exchange", "NSE"),
                sq_off=kw.get("sq_off", 0),
                stoploss=kw.get("stoploss", 0),
                trailing_sl=kw.get("trailing_sl", 0),
                reason=kw.get("reason", ""),
                meta=kw.get("meta"),
            )

            log.info(f"✅ Live order placed: {order_id}")
            return {"success": True, "order_id": str(order_id), "mode": "LIVE", "status": "PLACED"}

        except Exception as e:
            _log(
                symbol=kw["symbol"], action=kw["action"],
                order_type=kw["order_type"], variety=kw["variety"],
                product=self.product, quantity=kw["qty"],
                price=kw["price"], trigger_price=kw["trigger_price"],
                mode="LIVE", status="FAILED",
                strategy=kw.get("strategy", ""),
                exchange=kw.get("exchange", "NSE"),
                reason=str(e),
            )
            log.error(f"Order placement failed: {e}", exc_info=True)
            return {"error": str(e)}
