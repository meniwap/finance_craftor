from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.types import Candle, Intent, StrategyContext


class Strategy(ABC):
    @abstractmethod
    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        raise NotImplementedError

