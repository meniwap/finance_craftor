from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeStopExit:
    max_candles_in_trade: int

    def to_meta(self) -> dict[str, int]:
        return {"time_stop_candles": int(self.max_candles_in_trade)}

