from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.types import Balance, Order, OrderRequest, Position


class ExchangeClient(ABC):
    """Abstract exchange client. Implementations may use REST/WS internally."""

    @abstractmethod
    async def fetch_exchange_info(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_24h_tickers(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_klines(self, symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
        """Return raw kline arrays for the given symbol/interval."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_balances(self) -> list[Balance]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_positions(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    async def place_order(self, req: OrderRequest) -> Order:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def start_user_stream(self) -> str:
        """Return listenKey."""
        raise NotImplementedError

    @abstractmethod
    async def keepalive_user_stream(self, listen_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

