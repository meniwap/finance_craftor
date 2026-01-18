from __future__ import annotations

"""
Telegram alerts (optional).

Kept as a stub so the project has a clean integration point without forcing dependencies.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


class TelegramAlerter:
    def __init__(self, cfg: TelegramConfig) -> None:
        self._cfg = cfg

    async def send(self, text: str) -> None:
        # Implement with httpx + Telegram Bot API when enabling alerts.
        _ = text
        return None

