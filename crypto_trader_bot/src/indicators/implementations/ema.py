from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class EMA(Indicator):
    period: int
    name: str = "ema"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"ema": None},
                meta={"period": self.period, "needed": self.period},
            )
        closes = [c.close for c in candles]
        k = 2.0 / (self.period + 1.0)

        # seed with SMA of first period
        seed = sum(closes[: self.period]) / float(self.period)
        ema = seed
        for price in closes[self.period :]:
            ema = (price - ema) * k + ema
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"ema": ema},
            meta={"period": self.period},
        )

