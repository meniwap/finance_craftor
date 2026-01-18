from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.types import Candle, IndicatorResult


class Indicator(ABC):
    name: str

    @abstractmethod
    def compute(self, candles: list[Candle]) -> IndicatorResult:
        raise NotImplementedError

