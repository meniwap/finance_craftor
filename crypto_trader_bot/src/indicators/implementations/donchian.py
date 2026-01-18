from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class Donchian(Indicator):
    period: int = 20
    name: str = "donchian"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"high": None, "low": None, "mid": None},
                meta={"period": self.period},
            )
        window = candles[-self.period :]
        high = max(c.high for c in window)
        low = min(c.low for c in window)
        mid = (high + low) / 2.0
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"high": high, "low": low, "mid": mid},
            meta={"period": self.period},
        )
