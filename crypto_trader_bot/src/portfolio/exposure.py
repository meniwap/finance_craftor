from __future__ import annotations

from src.core.types import Position


def total_notional_usdt(positions: list[Position]) -> float:
    total = 0.0
    for p in positions:
        price = p.mark_price if p.mark_price is not None else p.entry_price
        total += abs(p.quantity) * float(price)
    return total

