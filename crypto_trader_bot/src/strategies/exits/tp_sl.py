from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TpSlExit:
    take_profit_pct: float
    stop_loss_pct: float

    def to_meta(self) -> dict[str, float]:
        return {"tp_pct": float(self.take_profit_pct), "sl_pct": float(self.stop_loss_pct)}

