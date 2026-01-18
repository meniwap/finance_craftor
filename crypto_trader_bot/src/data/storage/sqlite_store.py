from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.core.types import Candle, Fill, Order
from src.data.storage.base import Storage


class SQLiteStore(Storage):
    def __init__(self, path: str) -> None:
        self._path = str(Path(path))
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS candles (
              symbol TEXT NOT NULL,
              timeframe TEXT NOT NULL,
              open_time TEXT NOT NULL,
              close_time TEXT NOT NULL,
              open REAL NOT NULL,
              high REAL NOT NULL,
              low REAL NOT NULL,
              close REAL NOT NULL,
              volume REAL NOT NULL,
              PRIMARY KEY(symbol, timeframe, open_time)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
              order_id TEXT PRIMARY KEY,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              type TEXT NOT NULL,
              status TEXT NOT NULL,
              price REAL,
              orig_qty REAL NOT NULL,
              executed_qty REAL NOT NULL,
              update_time TEXT NOT NULL,
              raw_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
              trade_id TEXT PRIMARY KEY,
              order_id TEXT NOT NULL,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              price REAL NOT NULL,
              quantity REAL NOT NULL,
              fee_asset TEXT NOT NULL,
              fee_paid REAL NOT NULL,
              realized_pnl REAL,
              time TEXT NOT NULL,
              raw_json TEXT
            )
            """
        )
        self._conn.commit()

    def upsert_candles(self, candles: list[Candle]) -> None:
        cur = self._conn.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO candles
            (symbol,timeframe,open_time,close_time,open,high,low,close,volume)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    c.symbol,
                    c.timeframe,
                    c.open_time.isoformat(),
                    c.close_time.isoformat(),
                    c.open,
                    c.high,
                    c.low,
                    c.close,
                    c.volume,
                )
                for c in candles
            ],
        )
        self._conn.commit()

    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        cur = self._conn.cursor()
        rows = cur.execute(
            """
            SELECT * FROM candles
            WHERE symbol=? AND timeframe=?
            ORDER BY open_time DESC
            LIMIT ?
            """,
            (symbol, timeframe, limit),
        ).fetchall()

        out: list[Candle] = []
        for r in reversed(rows):
            out.append(
                Candle(
                    symbol=r["symbol"],
                    timeframe=r["timeframe"],
                    open_time=datetime.fromisoformat(r["open_time"]),
                    close_time=datetime.fromisoformat(r["close_time"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["volume"]),
                )
            )
        return out

    def record_order(self, order: Order) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO orders
            (order_id,symbol,side,type,status,price,orig_qty,executed_qty,update_time,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order.order_id,
                order.symbol,
                order.side.value,
                order.order_type.value,
                order.status.value,
                order.price,
                order.orig_qty,
                order.executed_qty,
                order.update_time.isoformat(),
                None,
            ),
        )
        self._conn.commit()

    def record_fill(self, fill: Fill) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO fills
            (trade_id,order_id,symbol,side,price,quantity,fee_asset,fee_paid,realized_pnl,time,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                fill.trade_id,
                fill.order_id,
                fill.symbol,
                fill.side.value,
                fill.price,
                fill.quantity,
                fill.fee_asset,
                fill.fee_paid,
                fill.realized_pnl,
                fill.time.isoformat(),
                None,
            ),
        )
        self._conn.commit()

