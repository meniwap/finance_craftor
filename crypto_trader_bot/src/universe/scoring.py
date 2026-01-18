from __future__ import annotations

from typing import Any


def score_tickers(
    tickers_24h: list[dict[str, Any]],
    *,
    allowed_symbols: set[str],
    min_quote_volume_24h: float,
    weights: dict[str, float] | None = None,
) -> list[tuple[float, str]]:
    """
    Score symbols by liquidity + trend + volatility using 24h stats.
    score = w_volume*log(quoteVolume) + w_trend*abs(priceChangePercent) + w_vol*(high-low)/last
    """
    w = {"volume": 1.0, "trend": 0.5, "vol": 0.5}
    if weights:
        w.update({k: float(v) for k, v in weights.items()})

    scored: list[tuple[float, str]] = []
    for t in tickers_24h:
        sym = t.get("symbol")
        if not sym or sym not in allowed_symbols:
            continue
        try:
            qv = float(t.get("quoteVolume", 0.0) or 0.0)
        except Exception:
            qv = 0.0
        if qv < min_quote_volume_24h:
            continue
        try:
            pct = abs(float(t.get("priceChangePercent", 0.0) or 0.0))
        except Exception:
            pct = 0.0
        try:
            high = float(t.get("highPrice", 0.0) or 0.0)
            low = float(t.get("lowPrice", 0.0) or 0.0)
            last = float(t.get("lastPrice", 0.0) or 0.0)
            vol = ((high - low) / last) if last else 0.0
        except Exception:
            vol = 0.0

        score = (w["volume"] * (qv ** 0.5)) + (w["trend"] * pct) + (w["vol"] * vol * 100)
        scored.append((score, sym))

    scored.sort(reverse=True)
    return scored
