from __future__ import annotations

from dataclasses import dataclass, field

from src.core.types import Candle, Intent, PositionSide, Signal, StrategyContext


@dataclass
class DemoImmediateLongStrategy:
    """
    Demo strategy for sanity-checking live order placement.

    Behavior:
    - On first candle close after startup, OPEN LONG once (fixed notional).
    - Optionally requests a time-based close after N candles via meta.
    """

    notional_usdt: float = 10.0
    time_stop_candles: int = 2
    tp_pct: float = 0.2
    sl_pct: float = 0.2
    _opened: set[str] = field(default_factory=set, init=False)

    def make_open_intent(self, symbol: str) -> Intent:
        return Intent(
            symbol=symbol,
            position_side=PositionSide.LONG,
            action="OPEN",
            notional_usdt=float(self.notional_usdt),
            signal=Signal.BUY,
            prefer_maker=False,
            meta={
                "tp_pct": float(self.tp_pct),
                "sl_pct": float(self.sl_pct),
                "time_stop_candles": int(self.time_stop_candles),
                "demo": True,
            },
        )

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        sym = context.symbol
        if sym in self._opened:
            return []
        self._opened.add(sym)
        return [self.make_open_intent(sym)]

