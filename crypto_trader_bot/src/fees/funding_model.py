from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FundingModel:
    """
    MVP funding estimator.

    Funding payment magnitude depends on position notional and funding rate.
    This model does not attempt to predict rate direction changes.
    """

    funding_rate: float  # e.g., 0.0001

    def estimate_payment(self, notional_usdt: float, *, periods: int = 1) -> float:
        return float(notional_usdt) * float(self.funding_rate) * int(periods)

