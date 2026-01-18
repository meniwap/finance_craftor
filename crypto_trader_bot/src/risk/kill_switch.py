from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class KillSwitch:
    halted: bool = False
    reason: str | None = None
    time: datetime | None = None

    def trigger(self, reason: str) -> None:
        self.halted = True
        self.reason = reason
        self.time = datetime.now(timezone.utc)

    def clear(self) -> None:
        self.halted = False
        self.reason = None
        self.time = None

