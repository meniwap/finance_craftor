from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class VWAP(Indicator):
    period: int = 20
    name: str = "vwap"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"vwap": None},
                meta={"period": self.period},
            )
        window = candles[-self.period :]
        pv = 0.0
        vol = 0.0
        for c in window:
            typical = (c.high + c.low + c.close) / 3.0
            pv += typical * c.volume
            vol += c.volume
        if vol <= 0:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"vwap": None},
                meta={"period": self.period},
            )
        vwap = pv / vol
        return IndicatorResult(name=self.name, is_ready=True, values={"vwap": vwap}, meta={"period": self.period})
