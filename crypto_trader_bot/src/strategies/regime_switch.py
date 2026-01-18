from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, Intent, StrategyContext


@dataclass(frozen=True)
class RegimeSwitchStrategy:
    trend_strategy: object
    range_strategy: object
    adx_key: str = "adx"
    adx_threshold: float = 20.0

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        adx = context.indicators.get(self.adx_key)
        adx_val = float(adx.values.get("adx") or 0.0) if adx and adx.is_ready else 0.0
        if adx_val >= self.adx_threshold:
            return self.trend_strategy.on_candle(candle, context)
        return self.range_strategy.on_candle(candle, context)
