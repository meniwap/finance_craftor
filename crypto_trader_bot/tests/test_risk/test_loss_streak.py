from __future__ import annotations

from datetime import datetime, timezone

from src.core.types import Fill, Side
from src.risk.guards.loss_streak import LossStreakGuard


def test_loss_streak_triggers():
    g = LossStreakGuard(limit=3)
    now = datetime.now(timezone.utc)
    for _ in range(3):
        g.on_fill(
            Fill(
                symbol="BTCUSDT",
                order_id="1",
                trade_id=str(_),
                side=Side.BUY,
                price=100.0,
                quantity=1.0,
                fee_asset="USDT",
                fee_paid=0.1,
                realized_pnl=-1.0,
                time=now,
            )
        )
    assert g.is_triggered() is True

