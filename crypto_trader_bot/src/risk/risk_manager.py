from __future__ import annotations

from dataclasses import dataclass

from src.core.types import FeesSnapshot, Intent, RiskDecision
from src.fees.breakeven import is_net_profitable_target
from src.portfolio.account_state import AccountState
from src.risk.guards.ladder_limits import LadderLimitsGuard
from src.risk.guards.loss_streak import LossStreakGuard
from src.risk.kill_switch import KillSwitch
from src.risk.portfolio_risk import PortfolioLimits, check_portfolio_limits
from src.risk.symbol_risk import SymbolLimits, allow_new_exposure


@dataclass
class RiskManager:
    portfolio_limits: PortfolioLimits
    symbol_limits: SymbolLimits
    loss_streak: LossStreakGuard
    ladder_limits: LadderLimitsGuard | None = None
    kill_switch: KillSwitch | None = None

    def validate_intent(
        self,
        intent: Intent,
        *,
        state: AccountState,
        fees: FeesSnapshot,
        last_price: float,
    ) -> RiskDecision:
        # Never block exits (CLOSE/REDUCE). Safety-first: allow reducing risk even when halted.
        if intent.action in {"CLOSE", "REDUCE"}:
            return RiskDecision(allowed=True)

        if self.kill_switch and self.kill_switch.halted:
            return RiskDecision(allowed=False, reason=self.kill_switch.reason, blocked_by="kill_switch")

        issues = check_portfolio_limits(state, self.portfolio_limits)
        if issues:
            return RiskDecision(allowed=False, reason=";".join(issues), blocked_by="portfolio_limits")

        if self.loss_streak.is_triggered():
            return RiskDecision(allowed=False, reason="loss_streak", blocked_by="loss_streak")

        pos = state.positions.get((intent.symbol, intent.position_side))
        if not allow_new_exposure(pos, self.symbol_limits):
            return RiskDecision(allowed=False, reason="liquidation_distance", blocked_by="symbol_limits")

        if self.ladder_limits and not self.ladder_limits.allow_intent(intent):
            return RiskDecision(allowed=False, reason="ladder_limits", blocked_by="ladder_limits")

        # Net breakeven gate (uses tp_pct from strategy meta as target)
        ignore_fees_gate = bool((intent.meta or {}).get("ignore_fees_gate", False))
        tp_pct = float(intent.meta.get("tp_pct", 0.0)) if intent.meta else 0.0
        if tp_pct > 0:
            if ignore_fees_gate:
                return RiskDecision(allowed=True)
            if not is_net_profitable_target(
                target_profit_pct=tp_pct,
                entry_price=float(last_price),
                notional_usdt=float(intent.notional_usdt),
                fees=fees,
                min_profit_over_breakeven_pct=0.0,
            ):
                return RiskDecision(allowed=False, reason="breakeven_gate", blocked_by="fees")

        return RiskDecision(allowed=True)

