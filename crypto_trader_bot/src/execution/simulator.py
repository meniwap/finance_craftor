from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.core.config import ExchangeConfig
from src.core.types import (
    Balance,
    Fill,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Side,
)
from src.exchange.adapters.symbol_mapper import SymbolMeta
from src.exchange.base import ExchangeClient
from src.execution.slippage import apply_slippage


@dataclass
class SimulatorExchange(ExchangeClient):
    cfg: ExchangeConfig
    symbol_meta: dict[str, SymbolMeta]
    maker_fee_rate: float
    taker_fee_rate: float
    slippage_bps: float
    initial_usdt: float = 1000.0
    spread_bps: float = 2.0
    partial_fill_pct: float = 1.0

    _order_seq: int = 0
    _positions: dict[tuple[str, PositionSide], Position] = field(default_factory=dict)
    _balances: dict[str, Balance] = field(default_factory=dict)
    _last_price: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._balances["USDT"] = Balance(asset="USDT", available=self.initial_usdt, total=self.initial_usdt)

    def update_mark_price(self, symbol: str, price: float) -> None:
        self._last_price[symbol] = float(price)
        for (sym, side), p in list(self._positions.items()):
            if sym != symbol:
                continue
            p.mark_price = float(price)
            p.unrealized_pnl = self._calc_unrealized(p)

    async def fetch_exchange_info(self) -> dict[str, Any]:
        # minimal exchangeInfo-like structure
        return {
            "symbols": [
                {
                    "symbol": m.symbol,
                    "status": m.status,
                    "baseAsset": m.base_asset,
                    "quoteAsset": m.quote_asset,
                    "pricePrecision": m.price_precision,
                    "quantityPrecision": m.quantity_precision,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": str(m.tick_size)},
                        {"filterType": "LOT_SIZE", "stepSize": str(m.step_size)},
                        {"filterType": "MIN_NOTIONAL", "minNotional": str(m.min_notional)},
                    ],
                }
                for m in self.symbol_meta.values()
            ]
        }

    async def fetch_24h_tickers(self) -> list[dict[str, Any]]:
        # MVP: return constant quoteVolume
        return [{"symbol": s, "quoteVolume": "100000000"} for s in self.symbol_meta.keys()]

    async def fetch_klines(self, symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
        _ = (symbol, interval, limit)
        return []

    async def fetch_balances(self) -> list[Balance]:
        return list(self._balances.values())

    async def fetch_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def place_order(self, req: OrderRequest) -> Order:
        self._order_seq += 1
        oid = str(self._order_seq)
        now = datetime.now(timezone.utc)

        last_price = self._last_price.get(req.symbol, req.price or 0.0)
        fill_price = apply_slippage(
            last_price,
            side=req.side.value,
            slippage_bps=self.slippage_bps,
            spread_bps=self.spread_bps,
        )
        exec_qty = float(req.quantity) * float(self.partial_fill_pct)
        notional = float(fill_price) * float(exec_qty)
        fee_rate = self.taker_fee_rate if req.order_type == OrderType.MARKET else self.maker_fee_rate
        fee_paid = notional * float(fee_rate)

        # Update balance (very simplified)
        usdt = self._balances["USDT"]
        usdt.available -= fee_paid
        usdt.total -= fee_paid

        pos_side = PositionSide.LONG if req.side == Side.BUY else PositionSide.SHORT
        key = (req.symbol, pos_side)
        if req.reduce_only:
            # MVP: reduce-only closes that side if exists
            self._positions.pop(key, None)
        else:
            self._positions[key] = Position(
                symbol=req.symbol,
                position_side=pos_side,
                quantity=float(exec_qty),
                entry_price=float(fill_price),
                mark_price=float(last_price),
                unrealized_pnl=0.0,
                leverage=None,
                liquidation_price=None,
                update_time=now,
            )

        fill = Fill(
            symbol=req.symbol,
            order_id=oid,
            trade_id=f"{oid}-1",
            side=req.side,
            price=float(fill_price),
            quantity=float(exec_qty),
            fee_asset="USDT",
            fee_paid=float(fee_paid),
            realized_pnl=None,
            time=now,
        )

        return Order(
            order_id=oid,
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            status=OrderStatus.FILLED,
            price=float(fill_price),
            orig_qty=float(req.quantity),
            executed_qty=float(exec_qty),
            update_time=now,
            reduce_only=req.reduce_only,
            meta={"fill": fill},
        )

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        # all orders fill immediately in MVP simulator
        return None

    async def start_user_stream(self) -> str:
        return "sim-listen-key"

    async def keepalive_user_stream(self, listen_key: str) -> None:
        return None

    async def close(self) -> None:
        return None

    def _calc_unrealized(self, p: Position) -> float:
        if p.mark_price is None:
            return 0.0
        if p.position_side == PositionSide.LONG:
            return (p.mark_price - p.entry_price) * p.quantity
        return (p.entry_price - p.mark_price) * p.quantity

