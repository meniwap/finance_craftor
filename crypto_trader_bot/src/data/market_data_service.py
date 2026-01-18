from __future__ import annotations

import asyncio
import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from src.core.types import Candle


class CandleDataSource(ABC):
    @abstractmethod
    async def stream(self, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        raise NotImplementedError


@dataclass(frozen=True)
class CsvCandleSource(CandleDataSource):
    """
    MVP datasource for paper/backtest wiring without depending on Binance history downloads.
    Expects a CSV with columns: timestamp,open,high,low,close,volume.
    """

    csv_path: str

    async def stream(self, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        p = Path(self.csv_path)
        with p.open("r", newline="") as f:
            r = csv.DictReader(f)
            rows = list(r)
        # stream as candle closes, one row at a time
        for row in rows:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            c = Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            yield c
            await asyncio.sleep(0)  # allow cooperative scheduling


class MarketDataService:
    def __init__(self, source: CandleDataSource) -> None:
        self._source = source

    async def stream_candles(self, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        async for c in self._source.stream(symbol, timeframe):
            yield c

    async def stream_many(self, symbols: list[str], timeframe: str) -> AsyncIterator[Candle]:
        """
        Merge candle streams for multiple symbols into a single async iterator.
        Ordering is best-effort; consumers should still key by (symbol,time).
        """

        q: asyncio.Queue[Candle] = asyncio.Queue()

        async def _pump(sym: str) -> None:
            async for c in self.stream_candles(sym, timeframe):
                await q.put(c)

        tasks = [asyncio.create_task(_pump(s)) for s in symbols]
        try:
            while True:
                c = await q.get()
                yield c
        finally:
            for t in tasks:
                t.cancel()

