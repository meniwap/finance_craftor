from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class RSI(Indicator):
    period: int = 14
    name: str = "rsi"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period + 1:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"rsi": None},
                meta={"period": self.period, "needed": self.period + 1},
            )

        closes = [c.close for c in candles]
        gains: list[float] = []
        losses: list[float] = []
        for prev, cur in zip(closes[:-1], closes[1:]):
            d = cur - prev
            gains.append(max(d, 0.0))
            losses.append(max(-d, 0.0))

        # Wilder's smoothing
        avg_gain = sum(gains[: self.period]) / self.period
        avg_loss = sum(losses[: self.period]) / self.period
        for g, l in zip(gains[self.period :], losses[self.period :]):
            avg_gain = (avg_gain * (self.period - 1) + g) / self.period
            avg_loss = (avg_loss * (self.period - 1) + l) / self.period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        state: dict[str, object] = {}
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"rsi": rsi},
            state=state,
            meta={"period": self.period},
        )

