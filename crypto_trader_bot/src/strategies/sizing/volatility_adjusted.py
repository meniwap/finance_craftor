from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VolatilityAdjustedSizing:
    base_notional_usdt: float = 100.0
    atr_target_pct: float = 1.0
    min_notional_usdt: float | None = None
    max_notional_usdt: float | None = None

    def compute_notional(self, *, atr: float, price: float) -> float | None:
        if atr <= 0 or price <= 0:
            return None
        atr_pct = (atr / price) * 100.0
        if atr_pct <= 0:
            return None
        # scale notional inversely to volatility
        notional = self.base_notional_usdt * (self.atr_target_pct / atr_pct)
        if self.max_notional_usdt is not None:
            notional = min(notional, self.max_notional_usdt)
        if self.min_notional_usdt is not None:
            notional = max(notional, self.min_notional_usdt)
        return notional
