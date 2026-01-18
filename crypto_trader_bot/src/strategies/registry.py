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
class StrategySpec:
    name: str
    label: str
    params: list[ParamSpec]


@dataclass(frozen=True)
class SizingSpec:
    name: str
    label: str
    params: list[ParamSpec]


class StrategyRegistry:
    def list_available(self) -> list[StrategySpec]:
        return [
            StrategySpec(
                "triple_confirm",
                "Triple Confirm",
                [
                    ParamSpec("rsi_long_min", "float", 55, 0, 100),
                    ParamSpec("rsi_long_max", "float", 70, 0, 100),
                    ParamSpec("rsi_short_max", "float", 45, 0, 100),
                    ParamSpec("long_only", "bool", True),
                    ParamSpec("max_extension_atr", "float", 0.8, 0, 5),
                    ParamSpec("max_candle_body_atr", "float", 1.2, 0, 5),
                    ParamSpec("tp_usdt", "float", 0.2, 0, 1000),
                    ParamSpec("sl_usdt", "float", 0.2, 0, 1000),
                ],
            ),
            StrategySpec(
                "multi_timeframe_trend",
                "Multi-Timeframe Trend",
                [
                    ParamSpec("ema_fast_key", "str", "ema_fast"),
                    ParamSpec("ema_slow_key", "str", "ema_slow"),
                    ParamSpec("confirm_timeframes", "list", ["15m", "1h"]),
                ],
            ),
            StrategySpec(
                "rsi_only",
                "RSI Mean Reversion",
                [
                    ParamSpec("oversold", "float", 30, 0, 100),
                    ParamSpec("overbought", "float", 70, 0, 100),
                ],
            ),
            StrategySpec(
                "composite",
                "Composite Strategy",
                [
                    ParamSpec("mode", "str", "all"),
                    ParamSpec("children", "list", []),
                ],
            ),
            StrategySpec(
                "rule_combo",
                "Rule Combo (UI)",
                [
                    ParamSpec("rules", "list", []),
                    ParamSpec("long_only", "bool", True),
                    ParamSpec("short_only", "bool", False),
                    ParamSpec("tp_usdt", "float", 0.2, 0, 1000),
                    ParamSpec("sl_usdt", "float", 0.2, 0, 1000),
                ],
            ),
            StrategySpec(
                "regime_switch",
                "Regime Switch (Trend/Range)",
                [
                    ParamSpec("adx_threshold", "float", 20.0, 5, 50),
                ],
            ),
        ]

    def list_sizing(self) -> list[SizingSpec]:
        return [
            SizingSpec("fixed_notional", "Fixed Notional", [ParamSpec("notional_usdt", "float", 50, 1, 100000)]),
            SizingSpec("fixed_risk", "Fixed Risk (%)", [ParamSpec("risk_pct", "float", 0.5, 0.05, 5), ParamSpec("max_notional_usdt", "float", 250, 1, 100000)]),
            SizingSpec("volatility_adjusted", "Volatility Adjusted", [ParamSpec("base_notional_usdt", "float", 100, 1, 100000), ParamSpec("atr_target_pct", "float", 1.0, 0.1, 10)]),
        ]
