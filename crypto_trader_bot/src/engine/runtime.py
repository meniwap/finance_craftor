from __future__ import annotations

import asyncio
import contextlib

from src.core.events import EventBus
from src.engine.coordinator import EngineCoordinator


class Runtime:
    def __init__(self, bus: EventBus, coordinator: EngineCoordinator) -> None:
        self._bus = bus
        self._coordinator = coordinator

    async def run(self) -> None:
        pump_task = asyncio.create_task(self._bus.pump())
        try:
            await self._coordinator.run()
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task

