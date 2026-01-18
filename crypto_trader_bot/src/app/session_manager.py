from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.app.bootstrap import build_runtime
from src.core.config import AppConfig, _deep_merge


@dataclass
class SessionEvent:
    type: str
    data: dict[str, Any]


@dataclass
class Session:
    session_id: str
    config: AppConfig
    base_config_path: str
    overrides: dict[str, Any]
    status: str = "created"
    events: list[SessionEvent] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    loop: asyncio.AbstractEventLoop | None = None
    thread: threading.Thread | None = None
    paused: bool = False


def _load_config_with_overrides(base_path: str, overrides: dict[str, Any]) -> AppConfig:
    p = Path(base_path)
    if not p.exists():
        raise FileNotFoundError(base_path)
    base = yaml.safe_load(p.read_text()) or {}
    merged = _deep_merge(base, overrides or {})
    return AppConfig.model_validate(merged)


class SessionManager:
    def __init__(self, store: Any | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._store = store

    def create_session(self, *, base_config_path: str, overrides: dict[str, Any] | None = None) -> Session:
        cfg = _load_config_with_overrides(base_config_path, overrides or {})
        session_id = uuid.uuid4().hex[:12]
        sess = Session(
            session_id=session_id,
            config=cfg,
            base_config_path=base_config_path,
            overrides=overrides or {},
        )
        event = SessionEvent(type="created", data={"base_config_path": base_config_path})
        sess.events.append(event)
        with self._lock:
            self._sessions[session_id] = sess
        if self._store:
            self._store.save_session(sess)
            self._store.append_event(session_id, event)
        return sess

    def get(self, session_id: str) -> Session:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            return self._sessions[session_id]

    def list(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def start(self, session_id: str) -> None:
        sess = self.get(session_id)
        if sess.task and not sess.task.done():
            raise RuntimeError("Session already running")

        # mark intent immediately (so UI can show it without racing the thread)
        sess.status = "starting"
        event0 = SessionEvent(type="start_requested", data={})
        sess.events.append(event0)
        if self._store:
            self._store.save_session(sess)
            self._store.append_event(session_id, event0)

        def _run() -> None:
            try:
                sess.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(sess.loop)
                runtime = build_runtime(cfg=sess.config, mode=sess.config.mode)
                sess.status = "running"
                event = SessionEvent(type="started", data={})
                sess.events.append(event)
                if self._store:
                    self._store.save_session(sess)
                    self._store.append_event(session_id, event)
                try:
                    sess.task = sess.loop.create_task(runtime.run())
                    sess.loop.run_until_complete(sess.task)
                    sess.status = "stopped"
                    event2 = SessionEvent(type="stopped", data={})
                    sess.events.append(event2)
                    if self._store:
                        self._store.save_session(sess)
                        self._store.append_event(session_id, event2)
                except asyncio.CancelledError:
                    # User-requested stop -> treat as normal stop (not failed)
                    sess.status = "stopped"
                    event2 = SessionEvent(type="stopped", data={"reason": "cancelled"})
                    sess.events.append(event2)
                    if self._store:
                        self._store.save_session(sess)
                        self._store.append_event(session_id, event2)
                except Exception as e:
                    sess.status = "failed"
                    event3 = SessionEvent(type="error", data={"error": str(e)})
                    sess.events.append(event3)
                    if self._store:
                        self._store.save_session(sess)
                        self._store.append_event(session_id, event3)
            except BaseException as e:
                # As a last resort, never let thread exceptions spam the terminal without recording state.
                if isinstance(e, asyncio.CancelledError):
                    sess.status = "stopped"
                    event2 = SessionEvent(type="stopped", data={"reason": "cancelled"})
                    sess.events.append(event2)
                    if self._store:
                        self._store.save_session(sess)
                        self._store.append_event(session_id, event2)
                    return
                sess.status = "failed"
                event3 = SessionEvent(type="error", data={"error": str(e)})
                sess.events.append(event3)
                if self._store:
                    self._store.save_session(sess)
                    self._store.append_event(session_id, event3)

        sess.thread = threading.Thread(target=_run, daemon=True)
        sess.thread.start()

    def stop(self, session_id: str) -> None:
        sess = self.get(session_id)
        if sess.loop and sess.task and not sess.task.done():
            sess.loop.call_soon_threadsafe(sess.task.cancel)
            event = SessionEvent(type="stop_requested", data={})
            sess.events.append(event)
            sess.status = "stopping"
            if self._store:
                self._store.save_session(sess)
                self._store.append_event(session_id, event)

    def pause(self, session_id: str) -> None:
        sess = self.get(session_id)
        sess.paused = True
        event = SessionEvent(type="pause_requested", data={})
        sess.events.append(event)
        if self._store:
            self._store.save_session(sess)
            self._store.append_event(session_id, event)

    def resume(self, session_id: str) -> None:
        sess = self.get(session_id)
        sess.paused = False
        event = SessionEvent(type="resume_requested", data={})
        sess.events.append(event)
        if self._store:
            self._store.save_session(sess)
            self._store.append_event(session_id, event)

    def record_command(self, session_id: str, *, name: str, params: dict[str, Any]) -> None:
        sess = self.get(session_id)
        event = SessionEvent(type="command", data={"name": name, "params": params})
        sess.events.append(event)
        if self._store:
            self._store.append_event(session_id, event)
