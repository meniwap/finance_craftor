from __future__ import annotations

from dataclasses import dataclass

from src.exchange.adapters.symbol_mapper import SymbolMeta


@dataclass(frozen=True)
class UniverseRegistry:
    symbols: list[str]
    symbol_meta: dict[str, SymbolMeta]

