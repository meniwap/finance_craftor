from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.monitoring.trade_store import TradeRecord, TradeStore


def rules_hash(rules: Any) -> str:
    """
    Stable hash for grouping rule sets. Uses JSON with sorted keys.
    """
    import json

    s = json.dumps(rules, sort_keys=True)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class StatsRow:
    mode: str
    timeframe: str
    direction: str
    rules_hash: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_pnl: float


def aggregate_stats(
    store: TradeStore,
    *,
    mode: str | None,
    timeframe: str | None,
    direction: str | None,
    limit_trades: int = 5000,
) -> list[StatsRow]:
    closed: list[TradeRecord] = store.list_closed(mode=mode, timeframe=timeframe, direction=direction, limit=limit_trades)
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for t in closed:
        if t.exit_time is None or t.realized_pnl_usdt is None:
            continue
        key = (t.mode, t.timeframe, t.direction, t.rules_hash)
        g = groups.get(key)
        if g is None:
            g = {"trades": 0, "wins": 0, "losses": 0, "total": 0.0}
            groups[key] = g
        g["trades"] += 1
        pnl = float(t.realized_pnl_usdt)
        g["total"] += pnl
        if pnl > 0:
            g["wins"] += 1
        elif pnl < 0:
            g["losses"] += 1

    rows: list[StatsRow] = []
    for (m, tf, d, rh), g in groups.items():
        trades = int(g["trades"])
        wins = int(g["wins"])
        losses = int(g["losses"])
        total = float(g["total"])
        rows.append(
            StatsRow(
                mode=m,
                timeframe=tf,
                direction=d,
                rules_hash=rh,
                trades=trades,
                wins=wins,
                losses=losses,
                win_rate=(wins / trades) if trades else 0.0,
                total_pnl=total,
                avg_pnl=(total / trades) if trades else 0.0,
            )
        )

    # Sort by total pnl desc, then trades desc
    rows.sort(key=lambda r: (r.total_pnl, r.trades), reverse=True)
    return rows


def current_loss_streak(trades: list[TradeRecord]) -> int:
    """
    Compute current loss streak from most recent closed trades.
    streak increments on pnl<0, resets on pnl>0. pnl==0 is ignored.
    """
    streak = 0
    for t in trades:
        if t.realized_pnl_usdt is None:
            continue
        pnl = float(t.realized_pnl_usdt)
        if pnl > 0:
            return 0
        if pnl < 0:
            streak += 1
    return streak

