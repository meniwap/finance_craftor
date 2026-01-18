from __future__ import annotations

from typing import Any

from src.exchange.adapters.symbol_mapper import SymbolMeta


def filter_trading_symbols(
    metas: dict[str, SymbolMeta],
    *,
    quote_asset: str,
    exclude: set[str],
    min_notional: float | None = None,
) -> dict[str, SymbolMeta]:
    out: dict[str, SymbolMeta] = {}
    for sym, m in metas.items():
        if m.status != "TRADING":
            continue
        if m.quote_asset != quote_asset:
            continue
        if sym in exclude:
            continue
        if min_notional is not None and m.min_notional and m.min_notional > min_notional:
            # if exchange min notional is higher than what we want to trade, skip (MVP guard)
            continue
        out[sym] = m
    return out


def select_top_n_by_quote_volume(
    tickers_24h: list[dict[str, Any]],
    *,
    allowed_symbols: set[str],
    top_n: int,
    min_quote_volume_24h: float,
) -> list[str]:
    scored: list[tuple[float, str]] = []
    for t in tickers_24h:
        sym = t.get("symbol")
        if not sym or sym not in allowed_symbols:
            continue
        qv = t.get("quoteVolume")
        try:
            qv_f = float(qv)
        except Exception:
            continue
        if qv_f < min_quote_volume_24h:
            continue
        scored.append((qv_f, sym))
    scored.sort(reverse=True)
    return [s for _, s in scored[:top_n]]

