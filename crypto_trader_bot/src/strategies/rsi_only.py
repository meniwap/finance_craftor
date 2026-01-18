from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, FeesSnapshot, Intent, PositionSide, Signal, StrategyContext
from src.strategies.base import Strategy
from src.strategies.entries.rsi_mean_reversion import RsiMeanReversionEntry
from src.strategies.exits.tp_sl import TpSlExit
from src.strategies.sizing.fixed_notional import FixedNotionalSizing


@dataclass
class RsiOnlyStrategy(Strategy):
    entry: RsiMeanReversionEntry
    sizing: FixedNotionalSizing
    exits: TpSlExit

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        rsi = context.indicators.get("rsi")
        if rsi is None:
            return []
        sig, side = self.entry.decide(rsi)
        if sig == Signal.NEUTRAL or side is None:
            return []

        notional = self.sizing.size()
        meta = {}
        meta.update(self.exits.to_meta())
        return [
            Intent(
                symbol=context.symbol,
                position_side=side,
                action="OPEN",
                notional_usdt=notional,
                signal=sig,
                prefer_maker=False,
                meta=meta,
            )
        ]

