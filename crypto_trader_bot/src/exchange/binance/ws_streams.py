from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import websockets


MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class WsConfig:
    ws_base_url: str


class UserStreamClient:
    def __init__(self, cfg: WsConfig, listen_key: str, handler: MessageHandler) -> None:
        self._cfg = cfg
        self._listen_key = listen_key
        self._handler = handler
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        url = f"{self._cfg.ws_base_url}/ws/{self._listen_key}"
        backoff = 0.5
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    backoff = 0.5
                    async for msg in ws:
                        if self._stop.is_set():
                            return
                        data = json.loads(msg)
                        await self._handler(data)
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

