from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.core.types import Balance, Fill, Order, OrderStatus, Position, PositionSide


@dataclass
class AccountState:
    balances: dict[str, Balance] = field(default_factory=dict)
    positions: dict[tuple[str, PositionSide], Position] = field(default_factory=dict)
    open_orders: dict[str, Order] = field(default_factory=dict)  # order_id -> Order

    realized_pnl_usdt: float = 0.0
    fees_paid_usdt: float = 0.0
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def set_balances(self, balances: list[Balance]) -> None:
        for b in balances:
            self.balances[b.asset] = b
        self.last_update = datetime.now(timezone.utc)

    def set_positions(self, positions: list[Position]) -> None:
        # Replace snapshot (do not keep stale positions around after close).
        # If we only "update" keys, a position that was closed (and disappears from the exchange snapshot)
        # would remain in memory forever, breaking close-detection logic.
        self.positions = {(p.symbol, p.position_side): p for p in positions}
        self.last_update = datetime.now(timezone.utc)

    def apply_order_update(self, order: Order) -> None:
        if order.status in {OrderStatus.CANCELED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}:
            self.open_orders.pop(order.order_id, None)
        else:
            self.open_orders[order.order_id] = order
        self.last_update = datetime.now(timezone.utc)

    def apply_fill(self, fill: Fill) -> None:
        self.fees_paid_usdt += float(fill.fee_paid)
        if fill.realized_pnl is not None:
            self.realized_pnl_usdt += float(fill.realized_pnl)
        self.last_update = datetime.now(timezone.utc)

