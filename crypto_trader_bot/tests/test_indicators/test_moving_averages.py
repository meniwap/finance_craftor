from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from src.core.types import Candle
from src.indicators.implementations.ema import EMA
from src.indicators.implementations.sma import SMA


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


def test_sma_ready_and_value():
    candles = _load_fixture()
    sma = SMA(period=5)
    res = sma.compute(candles)
    assert res.is_ready is True
    assert res.values["sma"] is not None


def test_ema_ready_and_value():
    candles = _load_fixture()
    ema = EMA(period=5)
    res = ema.compute(candles)
    assert res.is_ready is True
    assert res.values["ema"] is not None

