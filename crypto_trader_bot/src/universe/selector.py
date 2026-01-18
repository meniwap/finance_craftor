from __future__ import annotations

from src.core.config import UniverseConfig
from src.exchange.adapters.symbol_mapper import parse_exchange_info
from src.exchange.base import ExchangeClient
from src.universe.filters import filter_trading_symbols, select_top_n_by_quote_volume
from src.universe.scoring import score_tickers
from src.universe.registry import UniverseRegistry


class UniverseSelector:
    def __init__(self, cfg: UniverseConfig) -> None:
        self._cfg = cfg

    async def refresh(self, exchange: ExchangeClient) -> UniverseRegistry:
        exch_info = await exchange.fetch_exchange_info()
        metas = parse_exchange_info(exch_info)

        filtered = filter_trading_symbols(
            metas,
            quote_asset=self._cfg.quote_asset,
            exclude=set(self._cfg.exclude),
        )

        if self._cfg.symbols:
            symbols = [s for s in self._cfg.symbols if s in filtered]
        elif self._cfg.mode == "top_movers":
            tickers = await exchange.fetch_24h_tickers()
            direction = (self._cfg.movers_direction or "gainers").lower()
            scored: list[tuple[float, str]] = []
            for t in tickers:
                sym = t.get("symbol")
                if not sym or sym not in filtered:
                    continue
                try:
                    qv = float(t.get("quoteVolume", 0.0) or 0.0)
                except Exception:
                    qv = 0.0
                if qv < self._cfg.min_quote_volume_24h:
                    continue
                try:
                    pct = float(t.get("priceChangePercent"))
                except Exception:
                    continue
                scored.append((pct, sym))

            # gainers: highest % first; losers: lowest % first
            scored.sort(reverse=(direction != "losers"))
            symbols = [s for _, s in scored[: self._cfg.top_n]]
        elif self._cfg.mode == "top_n":
            tickers = await exchange.fetch_24h_tickers()
            symbols = select_top_n_by_quote_volume(
                tickers,
                allowed_symbols=set(filtered.keys()),
                top_n=self._cfg.top_n,
                min_quote_volume_24h=self._cfg.min_quote_volume_24h,
            )
        elif self._cfg.mode == "scored_top_n":
            tickers = await exchange.fetch_24h_tickers()
            scored = score_tickers(
                tickers,
                allowed_symbols=set(filtered.keys()),
                min_quote_volume_24h=self._cfg.min_quote_volume_24h,
                weights=self._cfg.score_weights,
            )
            symbols = [s for _, s in scored[: self._cfg.top_n]]
        else:
            # MVP supports top_n only; fallback to all filtered
            symbols = sorted(filtered.keys())

        sym_meta = {s: filtered[s] for s in symbols if s in filtered}
        return UniverseRegistry(symbols=symbols, symbol_meta=sym_meta)

