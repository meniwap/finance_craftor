from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Position


@dataclass(frozen=True)
class MaxLeverageGuard:
    max_leverage: int

    def allow_position(self, position: Position) -> bool:
        if position.leverage is None:
            return True
        return int(position.leverage) <= int(self.max_leverage)

