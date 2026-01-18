from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FillRecord:
    time: datetime
    symbol: str
    side: str
    price: float
    quantity: float
    fee_asset: str
    fee_paid: float
    realized_pnl: float | None
    order_id: str
    trade_id: str
    meta: dict[str, Any]


class FillStore:
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
                CREATE TABLE IF NOT EXISTS fills_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  time TEXT NOT NULL,
                  symbol TEXT NOT NULL,
                  side TEXT NOT NULL,
                  price REAL NOT NULL,
                  quantity REAL NOT NULL,
                  fee_asset TEXT NOT NULL,
                  fee_paid REAL NOT NULL,
                  realized_pnl REAL,
                  order_id TEXT NOT NULL,
                  trade_id TEXT NOT NULL,
                  meta_json TEXT
                )
                """
            )
            self._conn.commit()

    def record(self, rec: FillRecord) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO fills_log(time, symbol, side, price, quantity, fee_asset, fee_paid, realized_pnl, order_id, trade_id, meta_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec.time.isoformat(),
                    rec.symbol,
                    rec.side,
                    float(rec.price),
                    float(rec.quantity),
                    rec.fee_asset,
                    float(rec.fee_paid),
                    rec.realized_pnl,
                    rec.order_id,
                    rec.trade_id,
                    _json(rec.meta),
                ),
            )
            self._conn.commit()

    def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                "SELECT * FROM fills_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                out.append(
                    {
                        "time": r["time"],
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "price": r["price"],
                        "quantity": r["quantity"],
                        "fee_asset": r["fee_asset"],
                        "fee_paid": r["fee_paid"],
                        "realized_pnl": r["realized_pnl"],
                        "order_id": r["order_id"],
                        "trade_id": r["trade_id"],
                        "meta": _json_load(r["meta_json"]) if r["meta_json"] else {},
                    }
                )
            return out

    def sum_realized_pnl(self, *, symbol: str, start: datetime, end: datetime) -> float:
        """
        Sum realized_pnl for a symbol in [start, end]. Missing realized_pnl rows are ignored.
        """
        s = start.astimezone(timezone.utc).isoformat()
        e = end.astimezone(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT realized_pnl FROM fills_log
                WHERE symbol = ? AND time >= ? AND time <= ? AND realized_pnl IS NOT NULL
                """,
                (symbol, s, e),
            ).fetchall()
            total = 0.0
            for r in rows:
                try:
                    total += float(r["realized_pnl"])
                except Exception:
                    pass
            return total


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj, sort_keys=True)


def _json_load(s: str) -> Any:
    import json

    return json.loads(s)

