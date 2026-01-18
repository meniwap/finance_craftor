from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.core.types import Fill, Intent, Order, OrderRequest
from src.data.storage.base import Storage
from src.exchange.base import ExchangeClient
from src.execution.router import OrderRouter
from src.portfolio.account_state import AccountState


@dataclass
class OrderManager:
    exchange: ExchangeClient
    router: OrderRouter
    state: AccountState
    storage: Storage | None = None

    async def submit_intent(self, intent: Intent, *, last_price: float) -> Order:
        req = self.router.intent_to_order(intent, last_price=last_price)
        order = await self.exchange.place_order(req)
        self.state.apply_order_update(order)
        fill = order.meta.get("fill") if order.meta else None
        if fill is not None:
            self.on_fill(fill)
        if self.storage:
            self.storage.record_order(order)
        return order

    def on_order_update(self, order: Order) -> None:
        self.state.apply_order_update(order)
        if self.storage:
            self.storage.record_order(order)

    def on_fill(self, fill: Fill) -> None:
        self.state.apply_fill(fill)
        if self.storage:
            self.storage.record_fill(fill)

