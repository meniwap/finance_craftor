from __future__ import annotations

from dataclasses import dataclass

from src.portfolio.account_state import AccountState
from src.portfolio.exposure import total_notional_usdt


@dataclass(frozen=True)
class PortfolioLimits:
    max_total_positions: int
    max_total_notional_usdt: float
    daily_loss_limit_usdt: float


def check_portfolio_limits(state: AccountState, limits: PortfolioLimits) -> list[str]:
    issues: list[str] = []
    positions = list(state.positions.values())
    if len(positions) > limits.max_total_positions:
        issues.append("max_total_positions")
    if total_notional_usdt(positions) > limits.max_total_notional_usdt:
        issues.append("max_total_notional_usdt")
    if abs(state.realized_pnl_usdt) >= limits.daily_loss_limit_usdt and state.realized_pnl_usdt < 0:
        issues.append("daily_loss_limit")
    return issues

