from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


@dataclass(frozen=True)
class ADX(Indicator):
    period: int = 14
    name: str = "adx"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        if len(candles) < self.period + 1:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"adx": None, "di_plus": None, "di_minus": None},
                meta={"period": self.period},
            )

        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]

        trs: list[float] = []
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        for i in range(1, len(candles)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            trs.append(tr)
            plus_dm.append(pdm)
            minus_dm.append(mdm)

        if len(trs) < self.period:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"adx": None, "di_plus": None, "di_minus": None},
                meta={"period": self.period},
            )

        def _sum_last(arr: list[float], n: int) -> float:
            return sum(arr[-n:])

        tr_n = _sum_last(trs, self.period)
        pdm_n = _sum_last(plus_dm, self.period)
        mdm_n = _sum_last(minus_dm, self.period)

        if tr_n == 0:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"adx": None, "di_plus": None, "di_minus": None},
                meta={"period": self.period},
            )

        di_plus = 100.0 * (pdm_n / tr_n)
        di_minus = 100.0 * (mdm_n / tr_n)
        dx = 100.0 * abs(di_plus - di_minus) / max(di_plus + di_minus, 1e-9)

        # For simplicity, return last DX as ADX (smoothing can be added later)
        adx = dx
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"adx": adx, "di_plus": di_plus, "di_minus": di_minus},
            meta={"period": self.period},
        )
