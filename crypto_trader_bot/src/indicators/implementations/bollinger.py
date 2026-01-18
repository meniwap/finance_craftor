from __future__ import annotations

from dataclasses import dataclass

import math

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class BollingerBands(Indicator):
    period: int = 20
    stddevs: float = 2.0
    name: str = "bollinger"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"mid": None, "upper": None, "lower": None},
                meta={"period": self.period, "stddevs": self.stddevs, "needed": self.period},
            )
        closes = [c.close for c in candles[-self.period :]]
        mean = sum(closes) / float(self.period)
        var = sum((x - mean) ** 2 for x in closes) / float(self.period)
        sd = math.sqrt(var)
        upper = mean + self.stddevs * sd
        lower = mean - self.stddevs * sd
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"mid": mean, "upper": upper, "lower": lower},
            meta={"period": self.period, "stddevs": self.stddevs},
        )

