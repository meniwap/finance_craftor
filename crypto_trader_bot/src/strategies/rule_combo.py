from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.core.types import Candle, Intent, PositionSide, Signal, StrategyContext

log = logging.getLogger("rule_combo")


@dataclass(frozen=True)
class RuleComboStrategy:
    """
    UI-friendly strategy: user selects 1..N indicator-based rules.
    - If you pick only 2 rules, it will evaluate only those 2 (no hidden "3 indicators").
    - Entry when BUY rules pass (or SELL rules pass), depending on long_only/short_only.
    """

    rules: list[dict[str, Any]]
    notional_usdt: float
    long_only: bool = True
    short_only: bool = False
    invert_signals: bool = False
    tp_usdt: float | None = None
    sl_usdt: float | None = None
    tp_atr_mult: float | None = None
    sl_atr_mult: float | None = None
    break_even_pct: float | None = None
    trailing_stop_pct: float | None = None
    time_stop_candles: int | None = None
    ignore_fees_gate: bool = False

    def _rule_eval(self, rule: dict[str, Any], candle: Candle, ctx: StrategyContext) -> tuple[bool, bool, bool]:
        """
        Returns (ready, can_buy, can_sell)
        """
        rtype = str(rule.get("type", "")).strip().lower()
        ind = ctx.indicators

        if rtype == "ema_trend":
            fast_key = str(rule.get("fast", "ema_fast"))
            slow_key = str(rule.get("slow", "ema_slow"))
            fast = ind.get(fast_key)
            slow = ind.get(slow_key)
            if not (fast and slow and fast.is_ready and slow.is_ready):
                log.debug("EMA not ready for %s (fast=%s slow=%s)", candle.symbol,
                          fast.is_ready if fast else None, slow.is_ready if slow else None)
                return (False, False, False)
            fv = float(fast.values.get("ema") or 0.0)
            sv = float(slow.values.get("ema") or 0.0)
            buy_ok = fv > sv
            sell_ok = fv < sv
            log.info("📊 %s EMA: fast=%.4f slow=%.4f => LONG=%s SHORT=%s", candle.symbol, fv, sv, buy_ok, sell_ok)
            return (True, buy_ok, sell_ok)

        if rtype == "rsi_threshold":
            key = str(rule.get("key", "rsi"))
            r = ind.get(key)
            if not (r and r.is_ready):
                log.debug("RSI not ready for %s", candle.symbol)
                return (False, False, False)
            rv = float(r.values.get("rsi") or 0.0)
            long_min = float(rule.get("long_min", 55.0))
            short_max = float(rule.get("short_max", 45.0))
            buy_ok = rv >= long_min
            sell_ok = rv <= short_max
            log.info("📈 %s RSI: value=%.2f (LONG if >=%.0f, SHORT if <=%.0f) => LONG=%s SHORT=%s",
                     candle.symbol, rv, long_min, short_max, buy_ok, sell_ok)
            return (True, buy_ok, sell_ok)

        if rtype == "macd_signal":
            m = ind.get("macd")
            if not (m and m.is_ready):
                log.info("⏳ %s MACD: not ready (indicator=%s)", candle.symbol, m)
                return (False, False, False)
            macd = float(m.values.get("macd") or 0.0)
            sig = float(m.values.get("signal") or 0.0)
            buy_ok = macd > sig
            sell_ok = macd < sig
            log.info("📊 %s MACD: macd=%.6f signal=%.6f => LONG=%s SHORT=%s", candle.symbol, macd, sig, buy_ok, sell_ok)
            return (True, buy_ok, sell_ok)

        if rtype == "vwap_filter":
            v = ind.get("vwap")
            if not (v and v.is_ready):
                return (False, False, False)
            vwap = float(v.values.get("vwap") or 0.0)
            px = float(candle.close)
            return (True, px > vwap, px < vwap)

        if rtype == "adx_min":
            a = ind.get("adx")
            if not (a and a.is_ready):
                return (False, False, False)
            adx = float(a.values.get("adx") or 0.0)
            mn = float(rule.get("min", 15.0))
            ok = adx >= mn
            return (True, ok, ok)

        # unknown rule type: treat as not ready (blocks)
        return (False, False, False)

    def on_candle(self, candle: Candle, context: StrategyContext) -> list[Intent]:
        if not self.rules:
            log.debug("RuleCombo: no rules defined, skipping")
            return []

        ready_all = True
        can_buy = True
        can_sell = True
        rule_results: list[tuple[str, bool, bool, bool]] = []
        blocked_by: str | None = None
        for rule in self.rules:
            rtype = str(rule.get("type", ""))
            ready, buy_ok, sell_ok = self._rule_eval(rule, candle, context)
            rule_results.append((rtype, ready, buy_ok, sell_ok))
            if not ready:
                ready_all = False
                blocked_by = f"{rtype} (not ready)"
                break
            if not buy_ok and not sell_ok:
                blocked_by = f"{rtype} (no signal)"
            can_buy = can_buy and buy_ok
            can_sell = can_sell and sell_ok

        if not ready_all:
            log.info(
                "⏳ %s NOT READY: rules=%s (blocked_by=%s)",
                candle.symbol,
                [r.get("type") for r in self.rules],
                blocked_by,
            )
            return []

        raw_buy = bool(can_buy)
        raw_sell = bool(can_sell)

        # Contrarian mode: swap BUY/SELL signals (LONG <-> SHORT)
        if self.invert_signals:
            can_buy, can_sell = can_sell, can_buy

        if self.long_only:
            can_sell = False
        if self.short_only:
            can_buy = False

        final_buy = bool(can_buy)
        final_sell = bool(can_sell)

        # ALWAYS log evaluation results so user can see why entry was blocked (raw vs final after modifiers)
        if final_buy or final_sell:
            log.info(
                "✅ %s PASS: rules=%s results=%s raw=(buy=%s sell=%s) final=(buy=%s sell=%s) invert=%s long_only=%s short_only=%s",
                candle.symbol,
                [r.get("type") for r in self.rules],
                [(rtype, ready, buy, sell) for rtype, ready, buy, sell in rule_results],
                raw_buy,
                raw_sell,
                final_buy,
                final_sell,
                bool(self.invert_signals),
                bool(self.long_only),
                bool(self.short_only),
            )
        else:
            log.info(
                "❌ %s BLOCKED: rules=%s results=%s raw=(buy=%s sell=%s) final=(buy=%s sell=%s) invert=%s long_only=%s short_only=%s (blocked_by=%s)",
                candle.symbol,
                [r.get("type") for r in self.rules],
                [(rtype, ready, buy, sell) for rtype, ready, buy, sell in rule_results],
                raw_buy,
                raw_sell,
                final_buy,
                final_sell,
                bool(self.invert_signals),
                bool(self.long_only),
                bool(self.short_only),
                blocked_by,
            )

        meta: dict[str, Any] = {}
        if self.tp_usdt is not None:
            meta["tp_usdt"] = float(self.tp_usdt)
        if self.sl_usdt is not None:
            meta["sl_usdt"] = float(self.sl_usdt)
        if self.tp_atr_mult is not None:
            meta["tp_atr_mult"] = float(self.tp_atr_mult)
        if self.sl_atr_mult is not None:
            meta["sl_atr_mult"] = float(self.sl_atr_mult)
        if self.break_even_pct is not None:
            meta["break_even_pct"] = float(self.break_even_pct)
        if self.trailing_stop_pct is not None:
            meta["trailing_stop_pct"] = float(self.trailing_stop_pct)
        if self.time_stop_candles is not None:
            meta["time_stop_candles"] = int(self.time_stop_candles)
        if self.ignore_fees_gate:
            meta["ignore_fees_gate"] = True
        # Explainability: store which rules were used and a small snapshot of the indicator values at entry time.
        meta["rules"] = list(self.rules)
        keys: set[str] = set()
        for rule in self.rules:
            rtype = str(rule.get("type", "")).strip().lower()
            if rtype == "ema_trend":
                keys.add(str(rule.get("fast", "ema_fast")))
                keys.add(str(rule.get("slow", "ema_slow")))
            elif rtype == "rsi_threshold":
                keys.add(str(rule.get("key", "rsi")))
            elif rtype == "macd_signal":
                keys.add("macd")
            elif rtype == "vwap_filter":
                keys.add("vwap")
            elif rtype == "adx_min":
                keys.add("adx")
        snap: dict[str, Any] = {}
        for k in sorted(keys):
            ir = context.indicators.get(k)
            if ir:
                snap[k] = {"is_ready": bool(ir.is_ready), "values": dict(ir.values)}
        meta["indicators_snapshot"] = snap
        meta["entry_candle"] = {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "open_time": candle.open_time.isoformat(),
            "close_time": candle.close_time.isoformat(),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": float(candle.volume),
        }

        if can_buy:
            return [
                Intent(
                    symbol=context.symbol,
                    position_side=PositionSide.LONG,
                    action="OPEN",
                    notional_usdt=float(self.notional_usdt),
                    signal=Signal.BUY,
                    meta=meta,
                )
            ]
        if can_sell:
            return [
                Intent(
                    symbol=context.symbol,
                    position_side=PositionSide.SHORT,
                    action="OPEN",
                    notional_usdt=float(self.notional_usdt),
                    signal=Signal.SELL,
                    meta=meta,
                )
            ]
        return []
