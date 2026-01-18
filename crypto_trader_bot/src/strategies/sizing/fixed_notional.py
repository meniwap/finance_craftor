from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedNotionalSizing:
    notional_usdt: float

    def size(self) -> float:
        return float(self.notional_usdt)

