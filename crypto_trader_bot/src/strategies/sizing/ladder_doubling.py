from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LadderDoublingSizing:
    """
    Placeholder for martingale ladder sizing.

    Intentionally not wired by default. Must be guarded by risk/ladder_limits before enabling.
    """

    base_notional_usdt: float
    step: int = 0

    def size(self) -> float:
        return float(self.base_notional_usdt) * (2**self.step)

