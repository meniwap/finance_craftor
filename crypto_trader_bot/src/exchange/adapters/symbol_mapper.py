from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SymbolMeta:
    symbol: str
    status: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float


def _find_filter(filters: list[dict[str, Any]], ftype: str) -> dict[str, Any] | None:
    for f in filters:
        if f.get("filterType") == ftype:
            return f
    return None


def parse_exchange_info(exchange_info: dict[str, Any]) -> dict[str, SymbolMeta]:
    out: dict[str, SymbolMeta] = {}
    for s in exchange_info.get("symbols", []):
        filters = s.get("filters", [])
        price_f = _find_filter(filters, "PRICE_FILTER") or {}
        lot_f = _find_filter(filters, "LOT_SIZE") or {}
        min_notional_f = _find_filter(filters, "MIN_NOTIONAL") or _find_filter(filters, "NOTIONAL") or {}

        tick_size = float(price_f.get("tickSize", "0") or 0.0)
        step_size = float(lot_f.get("stepSize", "0") or 0.0)
        min_qty = float(lot_f.get("minQty", "0") or 0.0)
        min_notional = float(min_notional_f.get("notional", min_notional_f.get("minNotional", "0")) or 0.0)

        meta = SymbolMeta(
            symbol=s["symbol"],
            status=s.get("status", ""),
            base_asset=s.get("baseAsset", ""),
            quote_asset=s.get("quoteAsset", ""),
            price_precision=int(s.get("pricePrecision", 0)),
            quantity_precision=int(s.get("quantityPrecision", 0)),
            tick_size=tick_size,
            step_size=step_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        out[meta.symbol] = meta
    return out

