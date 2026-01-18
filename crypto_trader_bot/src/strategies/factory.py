from __future__ import annotations

from typing import Any

from src.core.config import StrategyConfig
from src.strategies.entries.rsi_mean_reversion import RsiMeanReversionEntry
from src.strategies.demo_immediate import DemoImmediateLongStrategy
from src.strategies.composite import CompositeStrategy
from src.strategies.exits.tp_sl import TpSlExit
from src.strategies.rsi_only import RsiOnlyStrategy
from src.strategies.sizing.fixed_notional import FixedNotionalSizing
from src.strategies.triple_confirm import TripleConfirmStrategy
from src.strategies.multi_timeframe_trend import MultiTimeframeTrendStrategy
from src.strategies.rule_combo import RuleComboStrategy
from src.strategies.regime_switch import RegimeSwitchStrategy


def build_strategy(cfg: StrategyConfig):
    if cfg.name == "demo_immediate_long":
        sizing_cfg = cfg.sizing or {}
        exits_cfg = (cfg.exits or {}).get("tp_sl", {})
        time_stop_cfg = (cfg.exits or {}).get("time_stop", {})
        return DemoImmediateLongStrategy(
            notional_usdt=float(sizing_cfg.get("notional_usdt", 10)),
            tp_pct=float(exits_cfg.get("take_profit_pct", 0.2)),
            sl_pct=float(exits_cfg.get("stop_loss_pct", 0.2)),
            time_stop_candles=int(time_stop_cfg.get("max_candles_in_trade", 2)),
        )

    if cfg.name == "rsi_mean_reversion" or cfg.name == "rsi_only":
        rsi_cfg = cfg.signals.get("rsi_threshold", {})
        sizing_cfg = cfg.sizing or {}
        exits_cfg = (cfg.exits or {}).get("tp_sl", {})

        entry = RsiMeanReversionEntry(
            oversold=float(rsi_cfg.get("oversold", 30)),
            overbought=float(rsi_cfg.get("overbought", 70)),
        )
        sizing = FixedNotionalSizing(notional_usdt=float(sizing_cfg.get("notional_usdt", 20)))
        exits = TpSlExit(
            take_profit_pct=float(exits_cfg.get("take_profit_pct", 0.4)),
            stop_loss_pct=float(exits_cfg.get("stop_loss_pct", 0.8)),
        )
        return RsiOnlyStrategy(entry=entry, sizing=sizing, exits=exits)

    if cfg.name == "triple_confirm":
        # indicators expected: ema_fast, ema_slow, rsi, atr
        sizing_cfg = cfg.sizing or {}
        params = (cfg.signals or {}).get("triple_confirm", {})
        return TripleConfirmStrategy(
            ema_fast_key=str(params.get("ema_fast_key", "ema_fast")),
            ema_slow_key=str(params.get("ema_slow_key", "ema_slow")),
            rsi_key=str(params.get("rsi_key", "rsi")),
            atr_key=str(params.get("atr_key", "atr")),
            rsi_long_min=float(params.get("rsi_long_min", 55.0)),
            rsi_long_max=(float(params["rsi_long_max"]) if "rsi_long_max" in params else None),
            rsi_short_max=float(params.get("rsi_short_max", 45.0)),
            long_only=bool(params.get("long_only", False)),
            atr_tp_mult=float(params.get("atr_tp_mult", 1.2)),
            atr_sl_mult=float(params.get("atr_sl_mult", 1.0)),
            max_extension_atr=(float(params["max_extension_atr"]) if "max_extension_atr" in params else None),
            max_candle_body_atr=(float(params["max_candle_body_atr"]) if "max_candle_body_atr" in params else None),
            notional_usdt=float(sizing_cfg.get("notional_usdt", 250.0)),
            tp_usdt=(float(params["tp_usdt"]) if "tp_usdt" in params else None),
            sl_usdt=(float(params["sl_usdt"]) if "sl_usdt" in params else None),
        )

    if cfg.name == "multi_timeframe_trend":
        sizing_cfg = cfg.sizing or {}
        params = (cfg.signals or {}).get("multi_timeframe_trend", {})
        confirm = params.get("confirm_timeframes", ["15m", "1h"])
        if not isinstance(confirm, list):
            confirm = [confirm]
        return MultiTimeframeTrendStrategy(
            ema_fast_key=str(params.get("ema_fast_key", "ema_fast")),
            ema_slow_key=str(params.get("ema_slow_key", "ema_slow")),
            confirm_timeframes=tuple(str(x) for x in confirm),
            notional_usdt=float(sizing_cfg.get("notional_usdt", 250.0)),
        )

    if cfg.name == "rule_combo":
        sizing_cfg = cfg.sizing or {}
        params = (cfg.signals or {}).get("rule_combo", {})
        rules = params.get("rules", [])
        if not isinstance(rules, list) or not rules:
            raise ValueError("rule_combo requires signals.rule_combo.rules list")
        return RuleComboStrategy(
            rules=rules,
            notional_usdt=float(sizing_cfg.get("notional_usdt", 50.0)),
            long_only=bool(params.get("long_only", True)),
            short_only=bool(params.get("short_only", False)),
            tp_usdt=(float(params["tp_usdt"]) if "tp_usdt" in params else None),
            sl_usdt=(float(params["sl_usdt"]) if "sl_usdt" in params else None),
            tp_atr_mult=(float(params["tp_atr_mult"]) if "tp_atr_mult" in params else None),
            sl_atr_mult=(float(params["sl_atr_mult"]) if "sl_atr_mult" in params else None),
            break_even_pct=(float(params["break_even_pct"]) if "break_even_pct" in params else None),
            trailing_stop_pct=(float(params["trailing_stop_pct"]) if "trailing_stop_pct" in params else None),
            time_stop_candles=(int(params["time_stop_candles"]) if "time_stop_candles" in params else None),
            ignore_fees_gate=bool(params.get("ignore_fees_gate", False)),
        )

    if cfg.name == "regime_switch":
        params = (cfg.signals or {}).get("regime_switch", {})
        trend_cfg = params.get("trend_strategy")
        range_cfg = params.get("range_strategy")
        if not trend_cfg or not range_cfg:
            raise ValueError("regime_switch requires signals.regime_switch.trend_strategy and range_strategy")
        trend = build_strategy(StrategyConfig.model_validate(trend_cfg))
        range_s = build_strategy(StrategyConfig.model_validate(range_cfg))
        return RegimeSwitchStrategy(
            trend_strategy=trend,
            range_strategy=range_s,
            adx_key=str(params.get("adx_key", "adx")),
            adx_threshold=float(params.get("adx_threshold", 20.0)),
        )

    if cfg.name == "composite":
        comp_cfg = (cfg.signals or {}).get("composite", {})
        mode = str(comp_cfg.get("mode", "all"))
        children_cfgs = comp_cfg.get("children", [])
        if not isinstance(children_cfgs, list) or not children_cfgs:
            raise ValueError("Composite strategy requires signals.composite.children list")
        children = []
        for child in children_cfgs:
            child_cfg = StrategyConfig.model_validate(child)
            children.append(build_strategy(child_cfg))
        return CompositeStrategy(mode=mode, children=children)

    raise ValueError(f"Unknown strategy name: {cfg.name}")

