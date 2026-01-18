from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.core.types import Intent, Candle, StrategyContext


@dataclass(frozen=True)
class CompositeStrategy:
    mode: Literal["all", "any"] = "all"
    children: list[object] = None  # list of strategies with on_candle

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        children = self.children or []
        intents_per_child: list[Intent] = []
        for child in children:
            out = child.on_candle(candle, context)
            if out:
                intents_per_child.append(out[0])
            else:
                intents_per_child.append(None)

        if self.mode == "any":
            for it in intents_per_child:
                if it is not None:
                    return [it]
            return []

        # mode == "all": require all children to agree on same direction
        if any(it is None for it in intents_per_child):
            return []
        first = intents_per_child[0]
        if any(it.position_side != first.position_side for it in intents_per_child if it is not None):
            return []

        # Merge meta (child meta overrides earlier keys if duplicated)
        meta = {}
        for it in intents_per_child:
            if it and it.meta:
                meta.update(it.meta)
        return [
            Intent(
                symbol=first.symbol,
                position_side=first.position_side,
                action=first.action,
                notional_usdt=first.notional_usdt,
                signal=first.signal,
                prefer_maker=first.prefer_maker,
                max_slippage_bps=first.max_slippage_bps,
                meta=meta,
            )
        ]
