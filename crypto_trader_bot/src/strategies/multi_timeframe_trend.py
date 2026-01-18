from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, Intent, PositionSide, Signal, StrategyContext


@dataclass(frozen=True)
class MultiTimeframeTrendStrategy:
    ema_fast_key: str = "ema_fast"
    ema_slow_key: str = "ema_slow"
    confirm_timeframes: tuple[str, ...] = ("15m", "1h")
    notional_usdt: float = 250.0

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        ind = context.indicators
        fast = ind.get(self.ema_fast_key)
        slow = ind.get(self.ema_slow_key)
        if not (fast and slow and fast.is_ready and slow.is_ready):
            return []
        fast_v = float(fast.values.get("ema") or 0.0)
        slow_v = float(slow.values.get("ema") or 0.0)

        bullish = fast_v > slow_v
        bearish = fast_v < slow_v

        # confirm across higher timeframes if provided in context
        for tf in self.confirm_timeframes:
            tf_ind = context.timeframes.get(tf, {})
            tf_fast = tf_ind.get(self.ema_fast_key)
            tf_slow = tf_ind.get(self.ema_slow_key)
            if not (tf_fast and tf_slow and tf_fast.is_ready and tf_slow.is_ready):
                return []
            tf_fast_v = float(tf_fast.values.get("ema") or 0.0)
            tf_slow_v = float(tf_slow.values.get("ema") or 0.0)
            if bullish and not (tf_fast_v > tf_slow_v):
                return []
            if bearish and not (tf_fast_v < tf_slow_v):
                return []

        if bullish:
            return [
                Intent(
                    symbol=context.symbol,
                    position_side=PositionSide.LONG,
                    action="OPEN",
                    notional_usdt=float(self.notional_usdt),
                    signal=Signal.BUY,
                )
            ]
        if bearish:
            return [
                Intent(
                    symbol=context.symbol,
                    position_side=PositionSide.SHORT,
                    action="OPEN",
                    notional_usdt=float(self.notional_usdt),
                    signal=Signal.SELL,
                )
            ]
        return []
