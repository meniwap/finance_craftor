from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DecisionRecord:
    time: datetime
    symbol: str
    action: str
    side: str
    allowed: bool
    blocked_by: str | None
    reason: str | None
    meta: dict[str, Any]


class DecisionStore:
    def __init__(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(p)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  time TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  action TEXT NOT NULL,
                  side TEXT NOT NULL,
                  allowed INTEGER NOT NULL,
                  blocked_by TEXT,
                  reason TEXT,
                  meta_json TEXT
                )
                """
            )
            self._conn.commit()

    def record(self, rec: DecisionRecord) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO decisions(time, symbol, action, side, allowed, blocked_by, reason, meta_json)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    rec.time.isoformat(),
                    rec.symbol,
                    rec.action,
                    rec.side,
                    1 if rec.allowed else 0,
                    rec.blocked_by,
                    rec.reason,
                    _json(rec.meta),
                ),
            )
            self._conn.commit()

    def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                out.append(
                    {
                        "time": r["time"],
                        "symbol": r["symbol"],
                        "action": r["action"],
                        "side": r["side"],
                        "allowed": bool(r["allowed"]),
                        "blocked_by": r["blocked_by"],
                        "reason": r["reason"],
                        "meta": _json_load(r["meta_json"]) if r["meta_json"] else {},
                    }
                )
            return out


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, sort_keys=True)


def _json_load(s: str) -> Any:
    import json

    return json.loads(s)
