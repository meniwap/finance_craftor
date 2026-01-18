from __future__ import annotations

from dataclasses import dataclass

from src.core.types import Candle, Intent, PositionSide, Signal, StrategyContext


@dataclass(frozen=True)
class TripleConfirmStrategy:
    """
    3-indicator confirmation strategy (5m recommended):
    - Trend: EMA(fast) vs EMA(slow)
    - Momentum: RSI above/below threshold
    - Volatility: ATR available (used to scale TP/SL)

    Entry rules:
    - LONG if all 3 confirm bullish
    - SHORT if all 3 confirm bearish

    Exits:
    - TP/SL derived from ATR (percent of price) and sent via algo orders (engine handles).
    """

    ema_fast_key: str = "ema_fast"
    ema_slow_key: str = "ema_slow"
    rsi_key: str = "rsi"
    atr_key: str = "atr"

    rsi_long_min: float = 55.0
    rsi_long_max: float | None = None  # if set, avoid buying when RSI is too high (overextended)
    rsi_short_max: float = 45.0
    long_only: bool = False

    atr_tp_mult: float = 1.2
    atr_sl_mult: float = 1.0

    # Anti-top filters (helpful when TP/SL are small vs 5m noise)
    max_extension_atr: float | None = None  # (price - ema_fast) / ATR must be <= this for LONG
    max_candle_body_atr: float | None = None  # abs(close-open) / ATR must be <= this (avoid huge impulse candles)

    notional_usdt: float = 250.0
    tp_usdt: float | None = None
    sl_usdt: float | None = None

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        ind = context.indicators
        fast = ind.get(self.ema_fast_key)
        slow = ind.get(self.ema_slow_key)
        rsi = ind.get(self.rsi_key)
        atr = ind.get(self.atr_key)

        if not (fast and slow and rsi and atr):
            return []
        if not (fast.is_ready and slow.is_ready and rsi.is_ready and atr.is_ready):
            return []

        fast_v = float(fast.values.get("ema") or 0.0)
        slow_v = float(slow.values.get("ema") or 0.0)
        rsi_v = float(rsi.values.get("rsi") or 0.0)
        atr_v = float(atr.values.get("atr") or 0.0)
        price = float(candle.close)
        if price <= 0 or atr_v <= 0:
            return []

        meta: dict[str, float] = {}
        if self.tp_usdt is not None:
            meta["tp_usdt"] = float(self.tp_usdt)
        if self.sl_usdt is not None:
            meta["sl_usdt"] = float(self.sl_usdt)
        if not meta:
            # ATR-based TP/SL as percentages
            meta["tp_pct"] = (atr_v * self.atr_tp_mult / price) * 100.0
            meta["sl_pct"] = (atr_v * self.atr_sl_mult / price) * 100.0

        bullish = (fast_v > slow_v) and (rsi_v >= self.rsi_long_min)
        bearish = (fast_v < slow_v) and (rsi_v <= self.rsi_short_max)

        # Long-only mode (disable shorts completely)
        if self.long_only:
            bearish = False

        if bullish:
            # Avoid buying at local tops: skip if RSI is too high
            if self.rsi_long_max is not None and rsi_v > float(self.rsi_long_max):
                return []

            # Avoid entries too far above EMA (overextended)
            if self.max_extension_atr is not None and atr_v > 0:
                extension = (price - fast_v) / atr_v
                if extension > float(self.max_extension_atr):
                    return []

            # Avoid entering right after a huge green impulse candle (often mean reverts)
            if self.max_candle_body_atr is not None and atr_v > 0:
                body = abs(float(candle.close) - float(candle.open)) / atr_v
                if body > float(self.max_candle_body_atr):
                    return []

            return [
                Intent(
                    symbol=context.symbol,
                    position_side=PositionSide.LONG,
                    action="OPEN",
                    notional_usdt=float(self.notional_usdt),
                    signal=Signal.BUY,
                    meta=meta,
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
                    meta=meta,
                )
            ]
        return []

