from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Intent


@dataclass(frozen=True)
class LadderLimitsGuard:
    max_steps: int
    max_total_notional_usdt: float

    def allow_intent(self, intent: Intent) -> bool:
        step = int(intent.meta.get("ladder_step", 0)) if intent.meta else 0
        series_notional = float(intent.meta.get("ladder_series_notional", intent.notional_usdt)) if intent.meta else float(intent.notional_usdt)
        if step > self.max_steps:
            return False
        if series_notional > self.max_total_notional_usdt:
            return False
        return True

