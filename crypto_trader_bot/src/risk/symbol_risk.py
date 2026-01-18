from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Position


@dataclass(frozen=True)
class SymbolLimits:
    min_liquidation_distance_pct: float


def liquidation_distance_pct(position: Position) -> float | None:
    if position.liquidation_price is None:
        return None
    price = position.mark_price if position.mark_price is not None else position.entry_price
    if price <= 0:
        return None
    return abs(price - float(position.liquidation_price)) / float(price) * 100.0


def allow_new_exposure(position: Position | None, limits: SymbolLimits) -> bool:
    if position is None:
        return True
    d = liquidation_distance_pct(position)
    if d is None:
        return True
    return d >= limits.min_liquidation_distance_pct

