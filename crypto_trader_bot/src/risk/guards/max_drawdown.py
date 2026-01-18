from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MaxDrawdownGuard:
    max_drawdown_pct: float
    equity_peak: float | None = None

    def update_equity(self, equity: float) -> None:
        if self.equity_peak is None:
            self.equity_peak = equity
        else:
            self.equity_peak = max(self.equity_peak, equity)

    def is_triggered(self, equity: float) -> bool:
        if self.equity_peak is None or self.equity_peak <= 0:
            return False
        dd = (self.equity_peak - equity) / self.equity_peak * 100.0
        return dd >= self.max_drawdown_pct

