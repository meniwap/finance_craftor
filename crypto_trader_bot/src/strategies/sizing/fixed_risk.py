from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedRiskSizing:
    risk_pct: float = 0.5
    max_notional_usdt: float | None = None
    min_notional_usdt: float | None = None

    def compute_notional(self, *, equity_usdt: float, stop_loss_pct: float) -> float | None:
        if equity_usdt <= 0 or stop_loss_pct <= 0:
            return None
        risk_usdt = equity_usdt * (self.risk_pct / 100.0)
        notional = risk_usdt / (stop_loss_pct / 100.0)
        if self.max_notional_usdt is not None:
            notional = min(notional, self.max_notional_usdt)
        if self.min_notional_usdt is not None:
            notional = max(notional, self.min_notional_usdt)
        return notional
