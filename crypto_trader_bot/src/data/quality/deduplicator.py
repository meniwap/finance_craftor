from __future__ import annotations

from src.core.types import Candle


def dedupe_candles(candles: list[Candle]) -> list[Candle]:
    """
    Remove duplicates by (symbol,timeframe,open_time). Keeps the last occurrence.
    Assumes candles are roughly ordered.
    """
    seen: dict[tuple[str, str, object], Candle] = {}
    for c in candles:
        key = (c.symbol, c.timeframe, c.open_time)
        seen[key] = c
    out = list(seen.values())
    out.sort(key=lambda c: c.open_time)
    return out

