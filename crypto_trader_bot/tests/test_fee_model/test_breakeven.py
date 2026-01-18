from __future__ import annotations

from src.core.types import FeesSnapshot
from src.fees.breakeven import breakeven_move_pct, is_net_profitable_target


def test_breakeven_increases_with_fees():
    fees_low = FeesSnapshot(maker_fee_rate=0.0, taker_fee_rate=0.0, slippage_bps=0.0)
    fees_high = FeesSnapshot(maker_fee_rate=0.001, taker_fee_rate=0.001, slippage_bps=10.0)

    be_low = breakeven_move_pct(entry_price=100.0, notional_usdt=100.0, fees=fees_low)
    be_high = breakeven_move_pct(entry_price=100.0, notional_usdt=100.0, fees=fees_high)

    assert be_high > be_low


def test_net_profit_gate_blocks_too_small_target():
    fees = FeesSnapshot(maker_fee_rate=0.0002, taker_fee_rate=0.0004, slippage_bps=2.0)
    ok = is_net_profitable_target(
        target_profit_pct=0.01,
        entry_price=100.0,
        notional_usdt=100.0,
        fees=fees,
        min_profit_over_breakeven_pct=0.0,
    )
    assert ok is False

