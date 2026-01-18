from __future__ import annotations

"""
Email alerts (optional) - stub.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str
    smtp_user: str
    smtp_password: str
    from_addr: str
    to_addr: str


class EmailAlerter:
    def __init__(self, cfg: EmailConfig) -> None:
        self._cfg = cfg

    async def send(self, subject: str, body: str) -> None:
        _ = (subject, body)
        return None

