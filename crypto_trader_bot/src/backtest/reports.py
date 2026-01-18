from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from src.backtest.engine import BacktestResult
from src.backtest.metrics import BacktestMetrics


def write_trades_csv(result: BacktestResult, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "symbol",
                "side",
                "qty",
                "entry_price",
                "exit_price",
                "entry_time",
                "exit_time",
                "gross_pnl",
                "fees",
                "funding",
                "net_pnl",
            ],
        )
        w.writeheader()
        for t in result.trades:
            w.writerow(
                {
                    "symbol": t.symbol,
                    "side": t.side.value,
                    "qty": t.qty,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "gross_pnl": t.gross_pnl,
                    "fees": t.fees,
                    "funding": t.funding,
                    "net_pnl": t.net_pnl,
                }
            )


def write_metrics_json(metrics: BacktestMetrics, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(metrics), indent=2, sort_keys=True))

