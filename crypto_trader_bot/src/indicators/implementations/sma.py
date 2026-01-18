from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class SMA(Indicator):
    period: int
    name: str = "sma"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"sma": None},
                meta={"period": self.period, "needed": self.period},
            )
        closes = [c.close for c in candles[-self.period :]]
        v = sum(closes) / float(self.period)
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"sma": v},
            meta={"period": self.period},
        )

