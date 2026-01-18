from __future__ import annotations

import math

from src.core.types import Intent, OrderRequest, OrderType, PositionSide, Side, TimeInForce
from src.exchange.adapters.symbol_mapper import SymbolMeta


def _floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step


def _ceil_to_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.ceil(x / step) * step


class OrderRouter:
    def __init__(self, symbol_meta: dict[str, SymbolMeta]) -> None:
        self._meta = symbol_meta

    def intent_to_order(self, intent: Intent, *, last_price: float) -> OrderRequest:
        meta = self._meta.get(intent.symbol)
        if meta is None:
            raise ValueError(f"Missing SymbolMeta for {intent.symbol}")

        # For CLOSE/REDUCE we prefer an explicit quantity if provided (avoid rounding re-computation).
        if intent.action != "OPEN" and intent.meta and "quantity" in intent.meta:
            qty = float(intent.meta["quantity"])
        else:
            qty = intent.notional_usdt / float(last_price)

        # default: do not exceed target notional too much
        qty = _floor_to_step(qty, meta.step_size)

        # Enforce Binance minimums.
        # - For OPEN: enforce both minQty and minNotional (ceil up).
        # - For CLOSE/REDUCE with explicit quantity: enforce only minQty/step (do not upsize close).
        min_qty_req = float(meta.min_qty or 0.0)
        if intent.action == "OPEN":
            min_notional_req = float(meta.min_notional or 0.0)
            qty_req = 0.0
            if min_qty_req > 0:
                qty_req = max(qty_req, min_qty_req)
            if min_notional_req > 0 and last_price > 0:
                qty_req = max(qty_req, min_notional_req / float(last_price))
            if qty < qty_req:
                qty = _ceil_to_step(qty_req, meta.step_size)
        else:
            if qty < min_qty_req and min_qty_req > 0:
                qty = _ceil_to_step(min_qty_req, meta.step_size)

        if qty <= 0:
            raise ValueError(f"Computed quantity <= 0 for {intent.symbol}")

        # For OPEN: LONG->BUY, SHORT->SELL
        # For CLOSE/REDUCE: use the opposite side with reduceOnly=true
        if intent.action == "OPEN":
            side = Side.BUY if intent.position_side == PositionSide.LONG else Side.SELL
        else:
            side = Side.SELL if intent.position_side == PositionSide.LONG else Side.BUY

        return OrderRequest(
            symbol=intent.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            time_in_force=None,
            reduce_only=(intent.action != "OPEN"),
            meta={"intent": intent.meta},
        )

