from __future__ import annotations


def apply_slippage(price: float, *, side: str, slippage_bps: float, spread_bps: float = 0.0) -> float:
    """
    side: 'BUY' or 'SELL'
    BUY pays up, SELL receives down (conservative).
    """
    bps = float(slippage_bps) / 10000.0
    spread = float(spread_bps) / 10000.0
    if side == "BUY":
        return float(price) * (1.0 + bps + spread)
    return float(price) * (1.0 - bps - spread)

