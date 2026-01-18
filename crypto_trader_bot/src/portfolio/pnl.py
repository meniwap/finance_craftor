from __future__ import annotations

from src.core.types import Position


def unrealized_pnl_usdt(positions: list[Position]) -> float:
    total = 0.0
    for p in positions:
        if p.unrealized_pnl is not None:
            total += float(p.unrealized_pnl)
    return total

