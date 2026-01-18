from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.core.types import Candle, FeesSnapshot, Intent, PositionSide, Signal, StrategyContext
from src.fees.fee_model import FeeModel
from src.indicators.factory import build_indicators
from src.portfolio.account_state import AccountState
from src.risk.risk_manager import RiskManager
from src.execution.slippage import apply_slippage
from src.strategies.base import Strategy


@dataclass
class OpenTrade:
    symbol: str
    side: PositionSide
    qty: float
    entry_price: float
    entry_time: datetime
    tp_pct: float
    sl_pct: float
    funding_paid: float = 0.0


@dataclass
class ClosedTrade:
    symbol: str
    side: PositionSide
    qty: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    gross_pnl: float
    fees: float
    funding: float
    net_pnl: float


@dataclass
class BacktestResult:
    trades: list[ClosedTrade]


@dataclass
class BacktestEngine:
    strategy: Strategy
    risk: RiskManager
    fees: FeesSnapshot
    indicator_cfg: dict
    initial_balance_usdt: float = 1000.0
    partial_fill_pct: float = 1.0

    _state: AccountState = field(default_factory=AccountState, init=False)
    _open: dict[str, OpenTrade] = field(default_factory=dict, init=False)
    _history: dict[str, list[Candle]] = field(default_factory=dict, init=False)
    _next_funding_time: dict[str, datetime] = field(default_factory=dict, init=False)

    def run(self, candles: list[Candle]) -> BacktestResult:
        indicators = build_indicators(self.indicator_cfg)
        fee_model = FeeModel(
            maker_fee_rate=self.fees.maker_fee_rate,
            taker_fee_rate=self.fees.taker_fee_rate,
            bnb_discount=0.0,
        )

        closed: list[ClosedTrade] = []

        for candle in candles:
            sym = candle.symbol
            hist = self._history.setdefault(sym, [])
            hist.append(candle)

            # update exits first (if we already have an open trade)
            if sym in self._open:
                t = self._open[sym]
                # apply funding on schedule (default every 8h) if funding_rate provided
                if self.fees.funding_rate is not None:
                    next_funding = self._next_funding_time.get(sym)
                    if next_funding is None:
                        # schedule from entry time
                        next_funding = t.entry_time + timedelta(hours=8)
                        self._next_funding_time[sym] = next_funding
                    while candle.close_time >= next_funding:
                        notional = t.entry_price * t.qty
                        rate = float(self.fees.funding_rate)
                        funding = -notional * rate if t.side == PositionSide.LONG else notional * rate
                        t.funding_paid += funding
                        self._state.realized_pnl_usdt += funding
                        next_funding = next_funding + timedelta(hours=8)
                        self._next_funding_time[sym] = next_funding

                exit_price = None
                if t.side == PositionSide.LONG:
                    tp_price = t.entry_price * (1.0 + t.tp_pct / 100.0)
                    sl_price = t.entry_price * (1.0 - t.sl_pct / 100.0)
                    hit_sl = candle.low <= sl_price
                    hit_tp = candle.high >= tp_price
                    if hit_sl and hit_tp:
                        exit_price = sl_price  # conservative
                    elif hit_sl:
                        exit_price = sl_price
                    elif hit_tp:
                        exit_price = tp_price
                else:
                    tp_price = t.entry_price * (1.0 - t.tp_pct / 100.0)
                    sl_price = t.entry_price * (1.0 + t.sl_pct / 100.0)
                    hit_sl = candle.high >= sl_price
                    hit_tp = candle.low <= tp_price
                    if hit_sl and hit_tp:
                        exit_price = sl_price  # conservative
                    elif hit_sl:
                        exit_price = sl_price
                    elif hit_tp:
                        exit_price = tp_price

                if exit_price is not None:
                    # apply slippage on exit (conservative)
                    exit_price = apply_slippage(
                        exit_price,
                        side="SELL" if t.side == PositionSide.LONG else "BUY",
                        slippage_bps=self.fees.slippage_bps,
                        spread_bps=0.5,
                    )
                    gross = (
                        (exit_price - t.entry_price) * t.qty
                        if t.side == PositionSide.LONG
                        else (t.entry_price - exit_price) * t.qty
                    )
                    notional = t.entry_price * t.qty
                    fees_paid = fee_model.fee_for_notional(notional, is_maker=False) + fee_model.fee_for_notional(
                        notional, is_maker=False
                    )
                    net = gross - fees_paid + t.funding_paid
                    closed.append(
                        ClosedTrade(
                            symbol=t.symbol,
                            side=t.side,
                            qty=t.qty,
                            entry_price=t.entry_price,
                            exit_price=exit_price,
                            entry_time=t.entry_time,
                            exit_time=candle.close_time,
                            gross_pnl=gross,
                            fees=fees_paid,
                            funding=t.funding_paid,
                            net_pnl=net,
                        )
                    )
                    self._state.realized_pnl_usdt += net
                    del self._open[sym]

            # compute indicators
            indicator_results = {name: ind.compute(hist) for name, ind in indicators.items()}

            ctx = StrategyContext(
                mode="backtest",
                symbol=sym,
                timeframe=candle.timeframe,
                indicators=indicator_results,
                fees=self.fees,
                positions={},
                balances={},
            )

            intents = self.strategy.on_candle(candle, ctx)
            if not intents or sym in self._open:
                continue  # one position per symbol in MVP backtest

            for intent in intents:
                decision = self.risk.validate_intent(intent, state=self._state, fees=self.fees, last_price=candle.close)
                if not decision.allowed:
                    continue
                tp = float(intent.meta.get("tp_pct", 0.4)) if intent.meta else 0.4
                sl = float(intent.meta.get("sl_pct", 0.8)) if intent.meta else 0.8

                entry_price = apply_slippage(
                    float(candle.close),
                    side="BUY" if intent.position_side == PositionSide.LONG else "SELL",
                    slippage_bps=self.fees.slippage_bps,
                    spread_bps=0.5,
                )
                qty = (float(intent.notional_usdt) / entry_price) * float(self.partial_fill_pct)
                self._open[sym] = OpenTrade(
                    symbol=sym,
                    side=intent.position_side,
                    qty=qty,
                    entry_price=entry_price,
                    entry_time=candle.close_time,
                    tp_pct=tp,
                    sl_pct=sl,
                )
                break

        return BacktestResult(trades=closed)

