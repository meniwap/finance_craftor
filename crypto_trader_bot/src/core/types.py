from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    # Conditional LIMIT-style orders (trigger + limit price) on Binance futures
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class IndicatorResult:
    name: str
    is_ready: bool
    values: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeesSnapshot:
    maker_fee_rate: float
    taker_fee_rate: float
    slippage_bps: float
    funding_rate: float | None = None


@dataclass(frozen=True)
class Intent:
    symbol: str
    position_side: PositionSide
    action: Literal["OPEN", "CLOSE", "REDUCE"]
    notional_usdt: float
    signal: Signal
    prefer_maker: bool = False
    max_slippage_bps: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool = False
    client_order_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Order:
    order_id: str
    client_order_id: str | None
    symbol: str
    side: Side
    order_type: OrderType
    status: OrderStatus
    price: float | None
    orig_qty: float
    executed_qty: float
    update_time: datetime
    reduce_only: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Fill:
    symbol: str
    order_id: str
    trade_id: str
    side: Side
    price: float
    quantity: float
    fee_asset: str
    fee_paid: float
    realized_pnl: float | None
    time: datetime
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    symbol: str
    position_side: PositionSide
    quantity: float
    entry_price: float
    mark_price: float | None = None
    unrealized_pnl: float | None = None
    leverage: int | None = None
    liquidation_price: float | None = None
    update_time: datetime | None = None


@dataclass
class Balance:
    asset: str
    available: float
    total: float
    update_time: datetime | None = None


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str | None = None
    blocked_by: str | None = None


@dataclass(frozen=True)
class StrategyContext:
    mode: Literal["backtest", "paper", "live"]
    symbol: str
    timeframe: str
    indicators: dict[str, IndicatorResult]
    fees: FeesSnapshot
    positions: dict[str, Position]
    balances: dict[str, Balance]
    timeframes: dict[str, dict[str, IndicatorResult]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

