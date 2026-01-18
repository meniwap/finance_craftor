from __future__ import annotations

from dataclasses import dataclass

from src.backtest.engine import BacktestResult


@dataclass(frozen=True)
class BacktestMetrics:
    net_pnl: float
    trade_count: int
    win_rate: float
    profit_factor: float
    max_drawdown: float


def compute_metrics(result: BacktestResult) -> BacktestMetrics:
    trades = result.trades
    net = sum(t.net_pnl for t in trades)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]
    win_rate = (len(wins) / len(trades)) if trades else 0.0
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # max drawdown on net equity curve (starting at 0)
    peak = 0.0
    eq = 0.0
    max_dd = 0.0
    for t in trades:
        eq += t.net_pnl
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)

    return BacktestMetrics(
        net_pnl=net,
        trade_count=len(trades),
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
    )

