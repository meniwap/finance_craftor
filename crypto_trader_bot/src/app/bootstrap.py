from __future__ import annotations

from src.core.config import AppConfig
from src.core.events import EventBus
from src.engine.coordinator import EngineCoordinator
from src.engine.runtime import Runtime


def build_runtime(cfg: AppConfig, mode: str) -> Runtime:
    bus = EventBus()
    coordinator = EngineCoordinator(bus=bus, cfg=cfg, mode=mode)
    return Runtime(bus=bus, coordinator=coordinator)

