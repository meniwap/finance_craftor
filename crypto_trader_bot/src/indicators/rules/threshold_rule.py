from __future__ import annotations

from dataclasses import dataclass

from src.core.types import IndicatorResult, Signal


@dataclass(frozen=True)
class ThresholdRule:
    """
    Generic threshold rule.

    Example (RSI):
      value_key='rsi', buy_below=30, sell_above=70
    """

    value_key: str
    buy_below: float | None = None
    sell_above: float | None = None

    def signal(self, indicator: IndicatorResult) -> Signal:
        if not indicator.is_ready:
            return Signal.NEUTRAL
        v = indicator.values.get(self.value_key)
        if v is None:
            return Signal.NEUTRAL
        v_f = float(v)
        if self.buy_below is not None and v_f <= self.buy_below:
            return Signal.BUY
        if self.sell_above is not None and v_f >= self.sell_above:
            return Signal.SELL
        return Signal.NEUTRAL

