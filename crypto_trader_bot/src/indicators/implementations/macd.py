from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, IndicatorResult
from src.indicators.base import Indicator


def _ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / float(period)
    ema = seed
    out = []
    for v in values[period:]:
        ema = (v - ema) * k + ema
        out.append(ema)
    return out


@dataclass(frozen=True)
class MACD(Indicator):
    fast: int = 12
    slow: int = 26
    signal: int = 9
    name: str = "macd"

    def compute(self, candles: list[Candle]) -> IndicatorResult:
        closes = [c.close for c in candles]
        if len(closes) < self.slow + self.signal:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"macd": None, "signal": None, "hist": None},
                meta={"fast": self.fast, "slow": self.slow, "signal": self.signal},
            )
        ema_fast = _ema_series(closes, self.fast)
        ema_slow = _ema_series(closes, self.slow)
        if not ema_fast or not ema_slow:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"macd": None, "signal": None, "hist": None},
                meta={"fast": self.fast, "slow": self.slow, "signal": self.signal},
            )
        # align by last values
        min_len = min(len(ema_fast), len(ema_slow))
        macd_series = [ema_fast[-min_len + i] - ema_slow[-min_len + i] for i in range(min_len)]
        sig_series = _ema_series(macd_series, self.signal)
        if not sig_series:
            return IndicatorResult(
                name=self.name,
                is_ready=False,
                values={"macd": None, "signal": None, "hist": None},
                meta={"fast": self.fast, "slow": self.slow, "signal": self.signal},
            )
        macd = macd_series[-1]
        signal = sig_series[-1]
        hist = macd - signal
        return IndicatorResult(
            name=self.name,
            is_ready=True,
            values={"macd": macd, "signal": signal, "hist": hist},
            meta={"fast": self.fast, "slow": self.slow, "signal": self.signal},
        )
