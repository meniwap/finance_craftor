from __future__ import annotations

from dataclasses import dataclass

from src.core.types import FeesSnapshot
from src.fees.fee_model import FeeModel
from src.fees.funding_model import FundingModel


@dataclass(frozen=True)
class BreakevenModel:
    fee_model: FeeModel
    slippage_bps: float

    def breakeven_cost_usdt(
        self,
        *,
        notional_usdt: float,
        entry_is_maker: bool,
        exit_is_maker: bool,
        funding_rate: float | None = None,
        funding_periods: int = 0,
    ) -> float:
        entry_fee = self.fee_model.fee_for_notional(notional_usdt, is_maker=entry_is_maker)
        exit_fee = self.fee_model.fee_for_notional(notional_usdt, is_maker=exit_is_maker)
        slip = float(notional_usdt) * (float(self.slippage_bps) / 10000.0)
        funding = 0.0
        if funding_rate is not None and funding_periods > 0:
            funding = FundingModel(funding_rate=funding_rate).estimate_payment(
                notional_usdt, periods=funding_periods
            )
        return entry_fee + exit_fee + slip + funding


def breakeven_move(
    *,
    entry_price: float,
    notional_usdt: float,
    fees: FeesSnapshot,
    entry_is_maker: bool = False,
    exit_is_maker: bool = False,
    funding_periods: int = 0,
) -> float:
    """
    Returns required favorable price move (absolute price delta) to break even after costs.
    """
    fm = FeeModel(
        maker_fee_rate=fees.maker_fee_rate,
        taker_fee_rate=fees.taker_fee_rate,
        bnb_discount=0.0,
    )
    be = BreakevenModel(fee_model=fm, slippage_bps=fees.slippage_bps)
    cost = be.breakeven_cost_usdt(
        notional_usdt=notional_usdt,
        entry_is_maker=entry_is_maker,
        exit_is_maker=exit_is_maker,
        funding_rate=fees.funding_rate,
        funding_periods=funding_periods,
    )
    qty = float(notional_usdt) / float(entry_price)
    if qty <= 0:
        return 0.0
    return cost / qty


def breakeven_move_pct(**kwargs) -> float:
    delta = breakeven_move(**kwargs)
    entry_price = float(kwargs["entry_price"])
    return (delta / entry_price) * 100.0 if entry_price else 0.0


def is_net_profitable_target(
    *,
    target_profit_pct: float,
    entry_price: float,
    notional_usdt: float,
    fees: FeesSnapshot,
    entry_is_maker: bool = False,
    exit_is_maker: bool = False,
    funding_periods: int = 0,
    min_profit_over_breakeven_pct: float = 0.0,
) -> bool:
    be_pct = breakeven_move_pct(
        entry_price=entry_price,
        notional_usdt=notional_usdt,
        fees=fees,
        entry_is_maker=entry_is_maker,
        exit_is_maker=exit_is_maker,
        funding_periods=funding_periods,
    )
    return float(target_profit_pct) >= (float(be_pct) + float(min_profit_over_breakeven_pct))

