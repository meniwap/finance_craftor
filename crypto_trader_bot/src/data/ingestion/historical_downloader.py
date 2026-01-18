from __future__ import annotations

from datetime import datetime, timezone

from src.core.types import Candle


def klines_to_candles(symbol: str, timeframe: str, klines: list[list]) -> list[Candle]:
    """
    Binance kline format:
      [
        [
          1499040000000,      // Open time
          "0.01634790",       // Open
          "0.80000000",       // High
          "0.01575800",       // Low
          "0.01577100",       // Close
          "148976.11427815",  // Volume
          1499644799999,      // Close time
          ...
        ]
      ]
    """
    out: list[Candle] = []
    for k in klines:
        open_time = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc)
        close_time = datetime.fromtimestamp(int(k[6]) / 1000, tz=timezone.utc)
        out.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            )
        )
    return out

