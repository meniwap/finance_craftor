from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class ATR(Indicator):
    period: int = 14
    name: str = "atr"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period + 1:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"atr": None},
                meta={"period": self.period, "needed": self.period + 1},
            )
        trs: list[float] = []
        for prev, cur in zip(candles[:-1], candles[1:]):
            tr = max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
            trs.append(tr)

        # Wilder smoothing (seed with SMA)
        atr = sum(trs[: self.period]) / self.period
        for tr in trs[self.period :]:
            atr = (atr * (self.period - 1) + tr) / self.period

        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"atr": atr},
            meta={"period": self.period},
        )

