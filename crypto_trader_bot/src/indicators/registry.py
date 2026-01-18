from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    default: Any
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    label: str
    params: list[ParamSpec]


class IndicatorRegistry:
    def list_available(self) -> list[IndicatorSpec]:
        return [
            IndicatorSpec("ema_fast", "EMA מהיר (Fast)", [ParamSpec("period", "int", 9, 2, 200)]),
            IndicatorSpec("ema_slow", "EMA איטי (Slow)", [ParamSpec("period", "int", 21, 2, 400)]),
            IndicatorSpec("rsi", "RSI", [ParamSpec("period", "int", 14, 2, 200)]),
            IndicatorSpec("macd", "MACD", [ParamSpec("fast", "int", 12, 2, 100), ParamSpec("slow", "int", 26, 2, 200), ParamSpec("signal", "int", 9, 2, 50)]),
            IndicatorSpec("vwap", "VWAP", [ParamSpec("period", "int", 20, 2, 200)]),
            IndicatorSpec("adx", "ADX", [ParamSpec("period", "int", 14, 2, 200)]),

            # Extra indicators (present in codebase; UI wiring for rules/filters can be added later)
            IndicatorSpec("atr", "ATR (בקרוב ב-UI)", [ParamSpec("period", "int", 14, 2, 200)]),
            IndicatorSpec("bollinger", "Bollinger (בקרוב ב-UI)", [ParamSpec("period", "int", 20, 2, 200), ParamSpec("stddevs", "float", 2.0, 0.5, 5.0)]),
            IndicatorSpec("stoch_rsi", "Stoch RSI (בקרוב ב-UI)", [ParamSpec("rsi_period", "int", 14, 2, 200), ParamSpec("stoch_period", "int", 14, 2, 200), ParamSpec("k_period", "int", 3, 1, 20), ParamSpec("d_period", "int", 3, 1, 20)]),
            IndicatorSpec("donchian", "Donchian (בקרוב ב-UI)", [ParamSpec("period", "int", 20, 2, 200)]),
            IndicatorSpec("ema", "EMA כללי (בקרוב ב-UI)", [ParamSpec("period", "int", 20, 2, 400)]),
            IndicatorSpec("sma", "SMA (בקרוב ב-UI)", [ParamSpec("period", "int", 20, 2, 400)]),
        ]
