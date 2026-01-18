from __future__ import annotations

import asyncio
import time


class SimpleRateLimiter:
    """
    Very small async limiter.

    Binance uses weight-based limits; later we can upgrade this to weight buckets.
    For MVP, this prevents accidental request bursts.
    """

    def __init__(self, max_per_sec: int = 8) -> None:
        self._max_per_sec = max_per_sec
        self._lock = asyncio.Lock()
        self._window_start = time.monotonic()
        self._count = 0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now - self._window_start >= 1.0:
                self._window_start = now
                self._count = 0

            if self._count >= self._max_per_sec:
                sleep_for = 1.0 - (now - self._window_start)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                self._window_start = time.monotonic()
                self._count = 0

            self._count += 1

