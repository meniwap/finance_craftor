from __future__ import annotations

from typing import Any

from src.indicators.base import Indicator
from src.indicators.implementations.adx import ADX
from src.indicators.implementations.atr import ATR
from src.indicators.implementations.bollinger import BollingerBands
from src.indicators.implementations.donchian import Donchian
from src.indicators.implementations.ema import EMA
from src.indicators.implementations.macd import MACD
from src.indicators.implementations.rsi import RSI
from src.indicators.implementations.sma import SMA
from src.indicators.implementations.stoch_rsi import StochRSI
from src.indicators.implementations.vwap import VWAP


def build_indicators(cfg: dict[str, Any]) -> dict[str, Indicator]:
    out: dict[str, Indicator] = {}
    for name, params in (cfg or {}).items():
        params = params or {}
        if name == "rsi":
            out["rsi"] = RSI(period=int(params.get("period", 14)))
        elif name == "sma":
            out["sma"] = SMA(period=int(params.get("period", 20)))
        elif name == "ema":
            out["ema"] = EMA(period=int(params.get("period", 20)))
        elif name == "ema_fast":
            out["ema_fast"] = EMA(period=int(params.get("period", 9)))
        elif name == "ema_slow":
            out["ema_slow"] = EMA(period=int(params.get("period", 21)))
        elif name == "atr":
            out["atr"] = ATR(period=int(params.get("period", 14)))
        elif name == "bollinger":
            out["bollinger"] = BollingerBands(
                period=int(params.get("period", 20)),
                stddevs=float(params.get("stddevs", 2.0)),
            )
        elif name == "macd":
            out["macd"] = MACD(
                fast=int(params.get("fast", 12)),
                slow=int(params.get("slow", 26)),
                signal=int(params.get("signal", 9)),
            )
        elif name == "stoch_rsi":
            out["stoch_rsi"] = StochRSI(
                rsi_period=int(params.get("rsi_period", 14)),
                stoch_period=int(params.get("stoch_period", 14)),
                k_period=int(params.get("k_period", 3)),
                d_period=int(params.get("d_period", 3)),
            )
        elif name == "adx":
            out["adx"] = ADX(period=int(params.get("period", 14)))
        elif name == "vwap":
            out["vwap"] = VWAP(period=int(params.get("period", 20)))
        elif name == "donchian":
            out["donchian"] = Donchian(period=int(params.get("period", 20)))
        else:
            raise ValueError(f"Unknown indicator: {name}")
    return out

