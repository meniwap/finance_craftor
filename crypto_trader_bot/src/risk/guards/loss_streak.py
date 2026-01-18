from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Fill


@dataclass
class LossStreakGuard:
    limit: int
    streak: int = 0

    def on_fill(self, fill: Fill) -> None:
        if fill.realized_pnl is None:
            return
        if float(fill.realized_pnl) < 0:
            self.streak += 1
        elif float(fill.realized_pnl) > 0:
            self.streak = 0

    def is_triggered(self) -> bool:
        return self.streak >= self.limit

