from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TradeRecord:
    trade_id: str
    mode: str  # live | paper
    symbol: str
    timeframe: str
    direction: str  # LONG | SHORT
    rules_hash: str
    entry_time: datetime
    exit_time: datetime | None
    realized_pnl_usdt: float | None
    rules: Any
    indicators_snapshot: Any
    meta: dict[str, Any]


class TradeStore:
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
                CREATE TABLE IF NOT EXISTS trades (
                  trade_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  timeframe TEXT NOT NULL,
                  direction TEXT NOT NULL,
                  rules_hash TEXT NOT NULL,
                  entry_time TEXT NOT NULL,
                  exit_time TEXT,
                  realized_pnl_usdt REAL,
                  rules_json TEXT,
                  indicators_json TEXT,
                  entry_candle_json TEXT,
                  meta_json TEXT
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_rules ON trades(rules_hash)")
            self._conn.commit()

    def open_trade(
        self,
        *,
        trade_id: str,
        mode: str,
        symbol: str,
        timeframe: str,
        direction: str,
        rules_hash: str,
        entry_time: datetime,
        rules: Any,
        indicators_snapshot: Any,
        meta: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO trades(
                  trade_id, mode, symbol, timeframe, direction, rules_hash,
                  entry_time, exit_time, realized_pnl_usdt, rules_json, indicators_json, entry_candle_json, meta_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trade_id,
                    mode,
                    symbol,
                    timeframe,
                    direction,
                    rules_hash,
                    _iso(entry_time),
                    None,
                    None,
                    _json(rules),
                    _json(indicators_snapshot),
                    _json((meta or {}).get("entry_candle")),
                    _json(meta or {}),
                ),
            )
            self._conn.commit()

    def close_trade(
        self,
        *,
        trade_id: str,
        exit_time: datetime,
        realized_pnl_usdt: float,
        meta_patch: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute("SELECT meta_json FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
            meta: dict[str, Any] = {}
            if row and row["meta_json"]:
                meta = _json_load(row["meta_json"]) or {}
            if meta_patch:
                meta.update(meta_patch)
            cur.execute(
                """
                UPDATE trades
                SET exit_time = ?, realized_pnl_usdt = ?, meta_json = ?
                WHERE trade_id = ?
                """,
                (_iso(exit_time), float(realized_pnl_usdt), _json(meta), trade_id),
            )
            self._conn.commit()

    def list_recent(self, *, mode: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            if mode:
                rows = cur.execute(
                    "SELECT * FROM trades WHERE mode = ? ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT ?",
                    (mode, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM trades ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [_row_to_dict(r) for r in rows]

    def list_by_rules_hash(
        self,
        *,
        rules_hash: str,
        mode: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            if mode:
                rows = cur.execute(
                    """
                    SELECT * FROM trades
                    WHERE rules_hash = ? AND mode = ?
                    ORDER BY COALESCE(exit_time, entry_time) DESC
                    LIMIT ?
                    """,
                    (rules_hash, mode, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    """
                    SELECT * FROM trades
                    WHERE rules_hash = ?
                    ORDER BY COALESCE(exit_time, entry_time) DESC
                    LIMIT ?
                    """,
                    (rules_hash, limit),
                ).fetchall()
            return [_row_to_dict(r) for r in rows]

    def list_open(self, *, mode: str | None = None) -> list[TradeRecord]:
        with self._lock:
            cur = self._conn.cursor()
            if mode:
                rows = cur.execute(
                    "SELECT * FROM trades WHERE exit_time IS NULL AND mode = ? ORDER BY entry_time ASC",
                    (mode,),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time ASC",
                ).fetchall()
            return [_row_to_record(r) for r in rows]

    def list_closed(
        self,
        *,
        mode: str | None = None,
        timeframe: str | None = None,
        direction: str | None = None,
        limit: int = 1000,
    ) -> list[TradeRecord]:
        q = "SELECT * FROM trades WHERE exit_time IS NOT NULL"
        params: list[Any] = []
        if mode:
            q += " AND mode = ?"
            params.append(mode)
        if timeframe:
            q += " AND timeframe = ?"
            params.append(timeframe)
        if direction:
            q += " AND direction = ?"
            params.append(direction)
        q += " ORDER BY exit_time DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(q, tuple(params)).fetchall()
            return [_row_to_record(r) for r in rows]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, sort_keys=True)


def _json_load(s: str) -> Any:
    import json

    return json.loads(s)


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "trade_id": r["trade_id"],
        "mode": r["mode"],
        "symbol": r["symbol"],
        "timeframe": r["timeframe"],
        "direction": r["direction"],
        "rules_hash": r["rules_hash"],
        "entry_time": r["entry_time"],
        "exit_time": r["exit_time"],
        "realized_pnl_usdt": r["realized_pnl_usdt"],
        "rules": _json_load(r["rules_json"]) if r["rules_json"] else None,
        "indicators_snapshot": _json_load(r["indicators_json"]) if r["indicators_json"] else None,
        "entry_candle": _json_load(r["entry_candle_json"]) if r["entry_candle_json"] else None,
        "meta": _json_load(r["meta_json"]) if r["meta_json"] else {},
    }


def _row_to_record(r: sqlite3.Row) -> TradeRecord:
    entry_time = datetime.fromisoformat(r["entry_time"])
    exit_time = datetime.fromisoformat(r["exit_time"]) if r["exit_time"] else None
    return TradeRecord(
        trade_id=r["trade_id"],
        mode=r["mode"],
        symbol=r["symbol"],
        timeframe=r["timeframe"],
        direction=r["direction"],
        rules_hash=r["rules_hash"],
        entry_time=entry_time,
        exit_time=exit_time,
        realized_pnl_usdt=float(r["realized_pnl_usdt"]) if r["realized_pnl_usdt"] is not None else None,
        rules=_json_load(r["rules_json"]) if r["rules_json"] else None,
        indicators_snapshot=_json_load(r["indicators_json"]) if r["indicators_json"] else None,
        meta=_json_load(r["meta_json"]) if r["meta_json"] else {},
    )

