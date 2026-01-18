from __future__ import annotations

from dataclasses import dataclass

from src.core.types import IndicatorResult, PositionSide, Signal
from src.indicators.rules.threshold_rule import ThresholdRule


@dataclass(frozen=True)
class RsiMeanReversionEntry:
    oversold: float = 30.0
    overbought: float = 70.0

    def decide(self, rsi: IndicatorResult) -> tuple[Signal, PositionSide | None]:
        rule = ThresholdRule(value_key="rsi", buy_below=self.oversold, sell_above=self.overbought)
        sig = rule.signal(rsi)
        if sig == Signal.BUY:
            return sig, PositionSide.LONG
        if sig == Signal.SELL:
            return sig, PositionSide.SHORT
        return Signal.NEUTRAL, None

