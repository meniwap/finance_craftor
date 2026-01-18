from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from src.core.types import OrderRequest, OrderType, PositionSide, Side, TimeInForce
from src.exchange.base import ExchangeClient
from src.exchange.adapters.symbol_mapper import SymbolMeta
from src.monitoring.logger import get_logger


@dataclass(frozen=True)
class BracketOrders:
    tp_order_id: str | None
    sl_order_id: str | None


class BracketManager:
    def __init__(
        self,
        exchange: ExchangeClient,
        symbol_meta: dict[str, SymbolMeta],
        *,
        tp_kind: str = "limit",
        sl_kind: str = "market",
        limit_offset_ticks: int = 0,
    ) -> None:
        self._exchange = exchange
        self._symbol_meta = symbol_meta
        self._tp_kind = tp_kind
        self._sl_kind = sl_kind
        self._limit_offset_ticks = limit_offset_ticks
        self._log = get_logger("brackets")

    def _round_to_tick(self, symbol: str, price: float, *, mode: str) -> float:
        meta = self._symbol_meta.get(symbol)
        tick = float(meta.tick_size) if meta else 0.0
        if tick <= 0:
            return price
        n = price / tick
        if mode == "ceil":
            return (int(n + 0.9999999999) * tick)
        if mode == "floor":
            return (int(n) * tick)
        return round(n) * tick

    async def _cancel_sl_orders(self, symbol: str) -> None:
        # Cancel any existing SL orders (both regular and algo listings, depending on exchange implementation).
        try:
            reg_open = await self._exchange.fetch_open_orders(symbol)
        except Exception:
            reg_open = []
        for o in reg_open:
            if str(o.get("type", "")).upper() in {"STOP", "STOP_MARKET"} and "orderId" in o:
                try:
                    await self._exchange.cancel_order(symbol, str(o["orderId"]))
                except Exception as e:
                    if "code=-2011" not in str(e):
                        raise
        try:
            algo_open = await self._exchange.fetch_open_algo_orders(symbol)
        except Exception:
            algo_open = []
        for o in algo_open:
            if str(o.get("type", "")).upper() in {"STOP", "STOP_MARKET"} and "algoId" in o:
                try:
                    await self._exchange.cancel_algo_order(int(o["algoId"]))
                except Exception as e:
                    if "code=-2011" not in str(e):
                        raise

    async def place_for_position(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        qty: float,
        entry_price: float,
        tp_pct: float,
        sl_pct: float,
        tp_usdt: float,
        sl_usdt: float,
        tp_levels: list[dict[str, Any]] | None = None,
    ) -> BracketOrders:
        if qty <= 0:
            return BracketOrders(None, None)

        meta = self._symbol_meta.get(symbol)
        tick = float(meta.tick_size) if meta else 0.0
        offset = (tick * self._limit_offset_ticks) if (tick > 0 and self._limit_offset_ticks > 0) else 0.0

        # IMPORTANT: If tp_usdt/sl_usdt is set, always use it (fixed USDT target).
        # Only use tp_pct/sl_pct if the USDT values are zero (ATR-based fallback).
        use_tp_usdt = tp_usdt > 0
        use_sl_usdt = sl_usdt > 0

        if position_side == PositionSide.LONG:
            close_side = Side.SELL
            if use_tp_usdt:
                tp_limit = self._round_to_tick(symbol, entry_price + (tp_usdt / qty), mode="ceil")
            elif tp_pct > 0:
                tp_limit = self._round_to_tick(symbol, entry_price * (1.0 + tp_pct / 100.0), mode="ceil")
            else:
                tp_limit = entry_price

            if use_sl_usdt:
                sl_limit = self._round_to_tick(symbol, entry_price - (sl_usdt / qty), mode="floor")
            elif sl_pct > 0:
                sl_limit = self._round_to_tick(symbol, entry_price * (1.0 - sl_pct / 100.0), mode="floor")
            else:
                sl_limit = entry_price

            tp_trigger = self._round_to_tick(symbol, tp_limit + offset, mode="ceil") if offset > 0 else tp_limit
            sl_trigger = self._round_to_tick(symbol, sl_limit + offset, mode="floor") if offset > 0 else sl_limit
        else:
            close_side = Side.BUY
            if use_tp_usdt:
                tp_limit = self._round_to_tick(symbol, entry_price - (tp_usdt / qty), mode="floor")
            elif tp_pct > 0:
                tp_limit = self._round_to_tick(symbol, entry_price * (1.0 - tp_pct / 100.0), mode="floor")
            else:
                tp_limit = entry_price

            if use_sl_usdt:
                sl_limit = self._round_to_tick(symbol, entry_price + (sl_usdt / qty), mode="ceil")
            elif sl_pct > 0:
                sl_limit = self._round_to_tick(symbol, entry_price * (1.0 + sl_pct / 100.0), mode="ceil")
            else:
                sl_limit = entry_price

            tp_trigger = self._round_to_tick(symbol, tp_limit - offset, mode="floor") if offset > 0 else tp_limit
            sl_trigger = self._round_to_tick(symbol, sl_limit - offset, mode="ceil") if offset > 0 else sl_limit

        self._log.info(
            "Bracket prices for %s: entry=%.6f tp_limit=%.6f sl_limit=%.6f (use_tp_usdt=%s use_sl_usdt=%s)",
            symbol, entry_price, tp_limit, sl_limit, use_tp_usdt, use_sl_usdt,
        )

        tp_order_id = None
        sl_order_id = None

        # TP levels: optional partial take profits
        if tp_levels:
            for lvl in tp_levels:
                qty_pct = float(lvl.get("qty_pct", 0))
                if qty_pct <= 0:
                    continue
                lvl_qty = qty * (qty_pct / 100.0)
                if lvl_qty <= 0:
                    continue
                if "usdt" in lvl:
                    target_usdt = float(lvl.get("usdt", 0.0))
                    if target_usdt <= 0:
                        continue
                    lvl_tp_price = (
                        entry_price + (target_usdt / qty) if position_side == PositionSide.LONG else entry_price - (target_usdt / qty)
                    )
                else:
                    pct = float(lvl.get("pct", 0.0))
                    if pct <= 0:
                        continue
                    lvl_tp_price = (
                        entry_price * (1.0 + pct / 100.0) if position_side == PositionSide.LONG else entry_price * (1.0 - pct / 100.0)
                    )
                if position_side == PositionSide.LONG:
                    lvl_limit = self._round_to_tick(symbol, lvl_tp_price, mode="ceil")
                    lvl_trigger = self._round_to_tick(symbol, lvl_limit + offset, mode="ceil") if offset > 0 else lvl_limit
                else:
                    lvl_limit = self._round_to_tick(symbol, lvl_tp_price, mode="floor")
                    lvl_trigger = self._round_to_tick(symbol, lvl_limit - offset, mode="floor") if offset > 0 else lvl_limit
                tp_req = OrderRequest(
                    symbol=symbol,
                    side=close_side,
                    order_type=(OrderType.TAKE_PROFIT_MARKET if self._tp_kind == "market" else OrderType.TAKE_PROFIT),
                    quantity=lvl_qty,
                    stop_price=lvl_trigger,
                    price=None if self._tp_kind == "market" else lvl_limit,
                    time_in_force=None if self._tp_kind == "market" else TimeInForce.GTC,
                    reduce_only=True,
                    meta={"bracket": "tp", "extra_params": {"workingType": "MARK_PRICE", "priceProtect": "TRUE"}},
                )
                try:
                    tp_order = await self._exchange.place_order(tp_req)
                    tp_order_id = tp_order.order_id
                except Exception as e:
                    self._log.warning("Failed placing TP level for %s: %s", symbol, e)
        elif tp_pct > 0 or tp_usdt > 0:
            tp_req = OrderRequest(
                symbol=symbol,
                side=close_side,
                order_type=(OrderType.TAKE_PROFIT_MARKET if self._tp_kind == "market" else OrderType.TAKE_PROFIT),
                quantity=qty,
                stop_price=tp_trigger,
                price=None if self._tp_kind == "market" else tp_limit,
                time_in_force=None if self._tp_kind == "market" else TimeInForce.GTC,
                reduce_only=True,
                meta={"bracket": "tp", "extra_params": {"workingType": "MARK_PRICE", "priceProtect": "TRUE"}},
            )
            try:
                tp_order = await self._exchange.place_order(tp_req)
                tp_order_id = tp_order.order_id
            except Exception as e:
                self._log.warning("Failed placing TP for %s: %s", symbol, e)

        if sl_pct > 0 or sl_usdt > 0:
            sl_req = OrderRequest(
                symbol=symbol,
                side=close_side,
                order_type=(OrderType.STOP_MARKET if self._sl_kind == "market" else OrderType.STOP),
                quantity=qty,
                stop_price=sl_trigger,
                price=None if self._sl_kind == "market" else sl_limit,
                time_in_force=None if self._sl_kind == "market" else TimeInForce.GTC,
                reduce_only=True,
                meta={"bracket": "sl", "extra_params": {"workingType": "MARK_PRICE", "priceProtect": "TRUE"}},
            )
            try:
                sl_order = await self._exchange.place_order(sl_req)
                sl_order_id = sl_order.order_id
            except Exception as e:
                self._log.warning("Failed placing SL for %s: %s", symbol, e)

        return BracketOrders(tp_order_id, sl_order_id)

    async def replace_sl_at_price(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        qty: float,
        stop_price: float,
    ) -> None:
        await self._cancel_sl_orders(symbol)

        if position_side == PositionSide.LONG:
            close_side = Side.SELL
            limit = self._round_to_tick(symbol, stop_price, mode="floor")
            trigger = self._round_to_tick(symbol, limit, mode="floor")
        else:
            close_side = Side.BUY
            limit = self._round_to_tick(symbol, stop_price, mode="ceil")
            trigger = self._round_to_tick(symbol, limit, mode="ceil")

        sl_req = OrderRequest(
            symbol=symbol,
            side=close_side,
            order_type=(OrderType.STOP_MARKET if self._sl_kind == "market" else OrderType.STOP),
            quantity=qty,
            stop_price=trigger,
            price=None if self._sl_kind == "market" else limit,
            time_in_force=None if self._sl_kind == "market" else TimeInForce.GTC,
            reduce_only=True,
            meta={"bracket": "sl", "extra_params": {"workingType": "MARK_PRICE", "priceProtect": "TRUE"}},
        )
        await self._exchange.place_order(sl_req)

    async def ensure_for_position(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        qty: float,
        entry_price: float,
        tp_pct: float,
        sl_pct: float,
        tp_usdt: float,
        sl_usdt: float,
    ) -> None:
        if qty <= 0:
            return
        if (tp_pct <= 0 and tp_usdt <= 0) and (sl_pct <= 0 and sl_usdt <= 0):
            return

        algo_open: list[dict[str, Any]] = []
        reg_open: list[dict[str, Any]] = []
        try:
            reg_open = await self._exchange.fetch_open_orders(symbol)
        except Exception as e:
            self._log.warning("Bracket ensure failed (fetch openOrders): %s", e)
        try:
            algo_open = await self._exchange.fetch_open_algo_orders(symbol)
        except Exception as e:
            # ok: not all clients/accounts support algo listings
            self._log.debug("Bracket ensure: fetch openAlgoOrders failed: %s", e)

        def _is_tp(o: dict[str, Any]) -> bool:
            # Regular orders have "type" field
            t = str(o.get("type", "") or "").upper()
            if t in {"TAKE_PROFIT", "TAKE_PROFIT_MARKET"}:
                return True
            # Algo orders: check if it's a conditional order for profit-taking
            # They may have "algoType" or just "side" and "triggerPrice"
            # If reduceOnly=True and triggerPrice > 0, it's a bracket order
            # For LONG position: TP has higher triggerPrice than current mark
            # We simplify: any algo order with triggerPrice and reduceOnly is a bracket
            if o.get("algoId") or o.get("strategyId"):
                # This is an algo order. Check if it looks like TP
                side = str(o.get("side", "")).upper()
                reduce_only = o.get("reduceOnly", False)
                trigger_price = float(o.get("triggerPrice", 0) or o.get("stopPrice", 0) or 0)
                # For simplicity: if it's a reduce-only algo order, count it
                if reduce_only and trigger_price > 0:
                    return True
            return False

        def _is_sl(o: dict[str, Any]) -> bool:
            # Regular orders have "type" field
            t = str(o.get("type", "") or "").upper()
            if t in {"STOP", "STOP_MARKET"}:
                return True
            # Same logic for algo orders — they're reduce-only conditional
            if o.get("algoId") or o.get("strategyId"):
                reduce_only = o.get("reduceOnly", False)
                trigger_price = float(o.get("triggerPrice", 0) or o.get("stopPrice", 0) or 0)
                if reduce_only and trigger_price > 0:
                    return True
            return False

        # For regular orders, use type-based detection
        # For algo orders, both TP and SL look similar (reduceOnly + triggerPrice)
        # So we count: if there are 2+ algo orders with reduceOnly+triggerPrice, assume TP+SL exist
        has_tp_reg = any(str(o.get("type", "") or "").upper() in {"TAKE_PROFIT", "TAKE_PROFIT_MARKET"} for o in reg_open)
        has_sl_reg = any(str(o.get("type", "") or "").upper() in {"STOP", "STOP_MARKET"} for o in reg_open)

        # Count algo bracket orders (reduceOnly + triggerPrice)
        algo_bracket_count = sum(
            1 for o in algo_open
            if o.get("reduceOnly", False) and float(o.get("triggerPrice", 0) or o.get("stopPrice", 0) or 0) > 0
        )

        # If we have 2+ algo brackets, assume both TP and SL are covered
        if algo_bracket_count >= 2:
            has_tp = True
            has_sl = True
        else:
            has_tp = has_tp_reg or (algo_bracket_count >= 1)
            has_sl = has_sl_reg or (algo_bracket_count >= 1)

        if has_tp and has_sl:
            return

        self._log.info("Bracket missing for %s (tp=%s sl=%s). Replacing.", symbol, has_tp, has_sl)
        await self.place_for_position(
            symbol=symbol,
            position_side=position_side,
            qty=qty,
            entry_price=entry_price,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            tp_usdt=tp_usdt,
            sl_usdt=sl_usdt,
        )

    async def cleanup(self, symbol: str) -> None:
        for _ in range(3):
            await self._exchange.cancel_all_open_algo_orders(symbol)
            await self._exchange.cancel_all_open_orders(symbol)

            algo_open = await self._exchange.fetch_open_algo_orders(symbol)
            reg_open = await self._exchange.fetch_open_orders(symbol)

            for o in algo_open:
                if "algoId" in o:
                    try:
                        await self._exchange.cancel_algo_order(int(o["algoId"]))
                    except Exception as e:
                        if "code=-2011" not in str(e):
                            raise
            for o in reg_open:
                if "orderId" in o:
                    try:
                        await self._exchange.cancel_order(symbol, str(o["orderId"]))
                    except Exception as e:
                        if "code=-2011" not in str(e):
                            raise

            algo_open2 = await self._exchange.fetch_open_algo_orders(symbol)
            reg_open2 = await self._exchange.fetch_open_orders(symbol)
            if not algo_open2 and not reg_open2:
                break
            await asyncio.sleep(0.3)
