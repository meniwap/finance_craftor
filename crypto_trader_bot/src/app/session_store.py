from __future__ import annotations

import sqlite3
from pathlib import Path
import threading
from typing import Any

from src.app.session_manager import Session, SessionEvent


class SessionStore:
    def __init__(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(p)
        # Uvicorn (and reload) can serve requests across different threads.
        # Allow cross-thread use and guard with a lock.
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id TEXT PRIMARY KEY,
                  base_config_path TEXT NOT NULL,
                  overrides_json TEXT NOT NULL,
                  status TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  data_json TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def save_session(self, sess: Session) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO sessions(session_id, base_config_path, overrides_json, status)
                VALUES(?,?,?,?)
                """,
                (sess.session_id, sess.base_config_path, _json(sess.overrides), sess.status),
            )
            self._conn.commit()

    def append_event(self, session_id: str, event: SessionEvent) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO session_events(session_id, type, data_json)
                VALUES(?,?,?)
                """,
                (session_id, event.type, _json(event.data)),
            )
            self._conn.commit()

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                "SELECT type, data_json FROM session_events WHERE session_id=? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            return [{"type": r["type"], "data": _json_load(r["data_json"])} for r in rows]


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, sort_keys=True)


def _json_load(s: str) -> Any:
    import json

    return json.loads(s)
