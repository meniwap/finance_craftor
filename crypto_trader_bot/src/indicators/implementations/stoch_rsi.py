from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator
from src.indicators.implementations.rsi import RSI


@dataclass(frozen=True)
class StochRSI(Indicator):
    rsi_period: int = 14
    stoch_period: int = 14
    k_period: int = 3
    d_period: int = 3
    name: str = "stoch_rsi"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.rsi_period + self.stoch_period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"k": None, "d": None},
                meta={"rsi_period": self.rsi_period, "stoch_period": self.stoch_period},
            )

        rsi_calc = RSI(period=self.rsi_period)
        rsi_series: list[float] = []
        for i in range(self.rsi_period, len(candles) + 1):
            r = rsi_calc.compute(candles[:i])
            if r.is_ready and r.values.get("rsi") is not None:
                rsi_series.append(float(r.values["rsi"]))
        if len(rsi_series) < self.stoch_period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"k": None, "d": None},
                meta={"rsi_period": self.rsi_period, "stoch_period": self.stoch_period},
            )

        window = rsi_series[-self.stoch_period :]
        rsi_min = min(window)
        rsi_max = max(window)
        if rsi_max == rsi_min:
            k = 50.0
        else:
            k = (rsi_series[-1] - rsi_min) / (rsi_max - rsi_min) * 100.0

        # smooth K and D with simple averages
        k_series = [k]
        for _ in range(self.k_period - 1):
            k_series.append(k)
        k_smoothed = sum(k_series) / len(k_series)

        d_series = [k_smoothed] * self.d_period
        d_smoothed = sum(d_series) / len(d_series)

        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"k": k_smoothed, "d": d_smoothed},
            meta={"rsi_period": self.rsi_period, "stoch_period": self.stoch_period},
        )
