from __future__ import annotations

from dataclasses import dataclass

from src.exchange.base import ExchangeClient
from src.portfolio.account_state import AccountState


@dataclass(frozen=True)
class ReconcileResult:
    ok: bool
    issues: list[str]


async def reconcile_state(exchange: ExchangeClient, state: AccountState) -> ReconcileResult:
    """
    MVP reconciliation: compare counts of positions and open orders.
    Later: deep compare quantities, avg entry prices, and order statuses.
    """
    issues: list[str] = []
    positions = await exchange.fetch_positions()
    balances = await exchange.fetch_balances()
    state.set_positions(positions)
    state.set_balances(balances)

    # open orders reconciliation is left for later (requires endpoint + order schema mapping)
    if len(state.positions) != len(positions):
        issues.append("position_count_mismatch")

    return ReconcileResult(ok=len(issues) == 0, issues=issues)

