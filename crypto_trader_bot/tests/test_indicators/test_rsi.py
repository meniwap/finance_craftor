from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.types import Candle
from src.indicators.implementations.rsi import RSI


def _load_fixture() -> list[Candle]:
    p = Path(__file__).parents[1] / "fixtures" / "sample_candles.csv"
    rows = list(csv.DictReader(p.open("r")))
    out: list[Candle] = []
    for row in rows:
        ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        out.append(
            Candle(
                symbol="BTCUSDT",
                timeframe="1m",
                open_time=ts,
                close_time=ts + timedelta(minutes=1),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return out


def test_rsi_not_ready_with_short_window():
    candles = _load_fixture()
    ind = RSI(period=14)
    res = ind.compute(candles[:10])
    assert res.is_ready is False
    assert res.values["rsi"] is None


def test_rsi_ready_and_in_range():
    candles = _load_fixture()
    ind = RSI(period=3)
    res = ind.compute(candles)
    assert res.is_ready is True
    assert 0.0 <= float(res.values["rsi"]) <= 100.0

