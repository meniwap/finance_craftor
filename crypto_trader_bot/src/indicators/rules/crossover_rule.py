from __future__ import annotations

from dataclasses import dataclass

from src.core.types import IndicatorResult, Signal


@dataclass(frozen=True)
class CrossoverRule:
    """
    Minimal crossover rule: compares two indicator values at the current candle.
    Up-cross -> BUY, down-cross -> SELL.

    For full crossover detection you'd track previous values; this is a starter.
    """

    fast_key: str
    slow_key: str

    def signal(self, fast: IndicatorResult, slow: IndicatorResult) -> Signal:
        if not (fast.is_ready and slow.is_ready):
            return Signal.NEUTRAL
        f = fast.values.get(self.fast_key)
        s = slow.values.get(self.slow_key)
        if f is None or s is None:
            return Signal.NEUTRAL
        if float(f) > float(s):
            return Signal.BUY
        if float(f) < float(s):
            return Signal.SELL
        return Signal.NEUTRAL

