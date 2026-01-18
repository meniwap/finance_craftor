from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, DefaultDict

from src.core.types import Candle, Fill, Order


@dataclass(frozen=True)
class Event:
    name: str
    time: datetime
    payload: dict[str, Any]


def candle_closed_event(candle: Candle) -> Event:
    return Event(name="CandleClosed", time=candle.close_time, payload={"candle": candle})


def order_update_event(order: Order) -> Event:
    return Event(name="OrderUpdate", time=order.update_time, payload={"order": order})


def fill_event(fill: Fill) -> Event:
    return Event(name="FillEvent", time=fill.time, payload={"fill": fill})


def funding_event(time: datetime, symbol: str, rate: float, payment: float) -> Event:
    return Event(
        name="FundingEvent", time=time, payload={"symbol": symbol, "rate": rate, "payment": payment}
    )


def risk_halt_event(time: datetime, reason: str) -> Event:
    return Event(name="RiskHalt", time=time, payload={"reason": reason})


def universe_updated_event(time: datetime, symbols: list[str]) -> Event:
    return Event(name="UniverseUpdated", time=time, payload={"symbols": symbols})


Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: DefaultDict[str, list[Handler]] = DefaultDict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    def subscribe(self, event_name: str, handler: Handler) -> None:
        self._subs[event_name].append(handler)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    async def pump(self) -> None:
        while True:
            event = await self._queue.get()
            handlers = list(self._subs.get(event.name, []))
            for h in handlers:
                await h(event)

