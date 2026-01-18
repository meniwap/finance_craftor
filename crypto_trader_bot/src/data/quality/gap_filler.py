from __future__ import annotations

from datetime import timedelta

from src.core.types import Candle


TIMEFRAME_TO_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


def detect_gaps(candles: list[Candle]) -> list[tuple[Candle, Candle]]:
    if not candles:
        return []
    tf = candles[0].timeframe
    step = TIMEFRAME_TO_SECONDS.get(tf)
    if not step:
        return []
    gaps: list[tuple[Candle, Candle]] = []
    for prev, cur in zip(candles, candles[1:]):
        expected = prev.open_time + timedelta(seconds=step)
        if cur.open_time > expected:
            gaps.append((prev, cur))
    return gaps


def fill_gaps_with_flat_candles(candles: list[Candle]) -> list[Candle]:
    """
    Optional repair: fill missing candles with flat candles using prev close.
    Use only in backtest/paper when configured; live should prefer backfill from exchange.
    """
    if not candles:
        return []
    tf = candles[0].timeframe
    step_sec = TIMEFRAME_TO_SECONDS.get(tf)
    if not step_sec:
        return candles
    out: list[Candle] = [candles[0]]
    for prev, cur in zip(candles, candles[1:]):
        t = prev.open_time
        while True:
            t_next = t + timedelta(seconds=step_sec)
            if t_next >= cur.open_time:
                break
            flat = Candle(
                symbol=prev.symbol,
                timeframe=prev.timeframe,
                open_time=t_next,
                close_time=t_next + timedelta(seconds=step_sec),
                open=prev.close,
                high=prev.close,
                low=prev.close,
                close=prev.close,
                volume=0.0,
            )
            out.append(flat)
            t = t_next
        out.append(cur)
    return out

