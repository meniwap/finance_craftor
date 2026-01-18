from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator

import websockets

from src.core.types import Candle
from src.data.market_data_service import CandleDataSource


def _interval_to_stream(timeframe: str) -> str:
    # Binance uses same strings for common timeframes (1m, 5m, 1h, ...)
    return timeframe


class BinanceFuturesKlineWsSource(CandleDataSource):
    def __init__(self, ws_base_url: str) -> None:
        self._ws_base_url = ws_base_url.rstrip("/")

    async def stream(self, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        sym = symbol.lower()
        interval = _interval_to_stream(timeframe)
        url = f"{self._ws_base_url}/ws/{sym}@kline_{interval}"

        backoff = 0.5
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    backoff = 0.5
                    async for msg in ws:
                        data = json.loads(msg)
                        # futures kline payload: { e: 'kline', ... , k: {...} }
                        k = data.get("k") or {}
                        if not k:
                            continue
                        is_closed = bool(k.get("x"))
                        if not is_closed:
                            continue
                        open_time = datetime.fromtimestamp(int(k["t"]) / 1000, tz=timezone.utc)
                        close_time = datetime.fromtimestamp(int(k["T"]) / 1000, tz=timezone.utc)
                        yield Candle(
                            symbol=symbol,
                            timeframe=timeframe,
                            open_time=open_time,
                            close_time=close_time,
                            open=float(k["o"]),
                            high=float(k["h"]),
                            low=float(k["l"]),
                            close=float(k["c"]),
                            volume=float(k["v"]),
                        )
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    async def stream_many(self, symbols: list[str], timeframe: str) -> AsyncIterator[Candle]:
        """
        Fan-in multiple per-symbol websocket streams into a single iterator.
        Intended for small symbol counts; for large universes you'd use combined streams.
        """
        q: asyncio.Queue[Candle] = asyncio.Queue()

        async def _pump(sym: str) -> None:
            async for c in self.stream(sym, timeframe):
                await q.put(c)

        tasks = [asyncio.create_task(_pump(s)) for s in symbols]
        try:
            while True:
                yield await q.get()
        finally:
            for t in tasks:
                t.cancel()

