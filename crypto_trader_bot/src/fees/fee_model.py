from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    maker_fee_rate: float
    taker_fee_rate: float
    bnb_discount: float = 0.0  # 0..1 applied multiplicatively

    def _apply_discount(self, rate: float) -> float:
        d = max(0.0, min(1.0, float(self.bnb_discount)))
        return rate * (1.0 - d)

    def fee_for_notional(self, notional_usdt: float, *, is_maker: bool) -> float:
        rate = self.maker_fee_rate if is_maker else self.taker_fee_rate
        rate = self._apply_discount(rate)
        return float(notional_usdt) * float(rate)

