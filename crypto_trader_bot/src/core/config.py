from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LoggingConfig(BaseModel):
    level: str = "INFO"


class ExchangeConfig(BaseModel):
    kind: str = "binance_futures_usdtm"
    base_url: str = "https://fapi.binance.com"
    ws_base_url: str = "wss://fstream.binance.com"
    recv_window_ms: int = 5000
    margin_mode: str | None = None
    position_mode: str | None = None
    leverage_default: int | None = None
    sim_spread_bps: float = 2.0
    sim_partial_fill_pct: float = 1.0


class UniverseConfig(BaseModel):
    mode: str = "top_n"
    quote_asset: str = "USDT"
    symbols: list[str] = Field(default_factory=list)  # if set, overrides selection
    top_n: int = 50
    min_quote_volume_24h: float = 0.0
    movers_direction: str = "gainers"  # gainers | losers
    exclude: list[str] = Field(default_factory=list)
    refresh_interval_sec: int = 3600
    score_weights: dict[str, float] = Field(default_factory=dict)


class MarketDataConfig(BaseModel):
    timeframe: str = "1m"
    candle_history: int = 500


class FeesConfig(BaseModel):
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.0004
    bnb_discount: float = 0.0
    slippage_bps: float = 2.0


class RiskConfig(BaseModel):
    live_enabled: bool = False
    max_total_positions: int = 10
    max_total_notional_usdt: float = 2000.0
    max_leverage: int = 3
    daily_loss_limit_usdt: float = 50.0
    loss_streak_limit: int = 5
    loss_streak_cooldown_sec: float = 600.0
    min_liquidation_distance_pct: float = 5.0


class StrategyConfig(BaseModel):
    name: str
    indicators: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, Any] = Field(default_factory=dict)
    sizing: dict[str, Any] = Field(default_factory=dict)
    exits: dict[str, Any] = Field(default_factory=dict)


class AppConfig(BaseModel):
    mode: str = "paper"
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    fees: FeesConfig = Field(default_factory=FeesConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategy: StrategyConfig


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(p.read_text()) or {}

    # allow simple includes by merging sibling configs if present
    # (kept minimal; can expand later)
    if (p.parent / "binance_futures.yaml").exists() and "exchange" in data:
        exch_overlay = yaml.safe_load((p.parent / "binance_futures.yaml").read_text()) or {}
        data = _deep_merge(exch_overlay, data)

    return AppConfig.model_validate(data)

