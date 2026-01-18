from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.types import Candle, Fill, Order


class Storage(ABC):
    @abstractmethod
    def init_schema(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert_candles(self, candles: list[Candle]) -> None:
        raise NotImplementedError

    @abstractmethod
    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    def record_order(self, order: Order) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_fill(self, fill: Fill) -> None:
        raise NotImplementedError

