from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import csv
import os
import math
import uuid

from src.backtest.engine import BacktestEngine
from src.backtest.metrics import compute_metrics
from src.backtest.reports import write_metrics_json, write_trades_csv
from src.core.config import AppConfig
from src.core.events import EventBus
from src.core.types import (
    Balance,
    Candle,
    FeesSnapshot,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    StrategyContext,
)
from src.data.ingestion.binance_kline_ws import BinanceFuturesKlineWsSource
from src.data.ingestion.historical_downloader import klines_to_candles
from src.data.quality.gap_filler import TIMEFRAME_TO_SECONDS
from src.exchange.adapters.auth import load_keys_from_env
from src.exchange.adapters.rate_limiter import SimpleRateLimiter
from src.exchange.binance.futures_client import BinanceFuturesUsdtmClient
from src.exchange.binance.ws_streams import UserStreamClient, WsConfig
from src.execution.order_manager import OrderManager
from src.execution.router import OrderRouter
from src.execution.bracket_manager import BracketManager
from src.execution.simulator import SimulatorExchange
from src.indicators.factory import build_indicators
from src.monitoring.logger import get_logger, setup_logging
from src.monitoring.decision_store import DecisionRecord, DecisionStore
from src.monitoring.fill_store import FillRecord, FillStore
from src.monitoring.trade_store import TradeStore
from src.monitoring.stats import rules_hash
from src.portfolio.account_state import AccountState
from src.portfolio.exposure import total_notional_usdt
from src.risk.guards.loss_streak import LossStreakGuard
from src.risk.risk_manager import RiskManager
from src.risk.kill_switch import KillSwitch
from src.risk.portfolio_risk import PortfolioLimits
from src.risk.symbol_risk import SymbolLimits
from src.strategies.factory import build_strategy
from src.strategies.demo_immediate import DemoImmediateLongStrategy
from src.universe.selector import UniverseSelector

from src.exchange.adapters.symbol_mapper import SymbolMeta
from src.core.types import Intent, OrderRequest, Side, Signal, TimeInForce
from src.universe.registry import UniverseRegistry
from src.strategies.sizing.fixed_risk import FixedRiskSizing
from src.strategies.sizing.volatility_adjusted import VolatilityAdjustedSizing


class EngineCoordinator:
    def __init__(self, bus: EventBus, cfg: AppConfig, mode: str) -> None:
        self._bus = bus
        self._cfg = cfg
        self._mode = mode

    async def run(self) -> None:
        if self._mode == "backtest":
            await self._run_backtest()
            return
        if self._mode == "paper":
            await self._run_paper()
            return
        if self._mode == "live":
            await self._run_live()
            return

        # paper/live wiring is implemented in later todos
        while True:
            await asyncio.sleep(1.0)

    async def _run_backtest(self) -> None:
        cfg = self._cfg
        fees = FeesSnapshot(
            maker_fee_rate=cfg.fees.maker_fee_rate,
            taker_fee_rate=cfg.fees.taker_fee_rate,
            slippage_bps=cfg.fees.slippage_bps,
            funding_rate=None,
        )
        strategy = build_strategy(cfg.strategy)
        risk = RiskManager(
            portfolio_limits=PortfolioLimits(
                max_total_positions=cfg.risk.max_total_positions,
                max_total_notional_usdt=cfg.risk.max_total_notional_usdt,
                daily_loss_limit_usdt=cfg.risk.daily_loss_limit_usdt,
            ),
            symbol_limits=SymbolLimits(min_liquidation_distance_pct=cfg.risk.min_liquidation_distance_pct),
            loss_streak=LossStreakGuard(limit=cfg.risk.loss_streak_limit),
            ladder_limits=None,
            kill_switch=KillSwitch(),
        )

        fixture_csv = Path("tests/fixtures/sample_candles.csv")
        rows = list(csv.DictReader(fixture_csv.open("r")))
        candles: list[Candle] = []
        for row in rows:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            candles.append(
                Candle(
                    symbol="BTCUSDT",
                    timeframe=cfg.market_data.timeframe,
                    open_time=ts,
                    close_time=ts + timedelta(minutes=1),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )

        engine = BacktestEngine(
            strategy=strategy,
            risk=risk,
            fees=fees,
            indicator_cfg=cfg.strategy.indicators,
        )
        result = engine.run(candles)
        metrics = compute_metrics(result)

        write_trades_csv(result, "reports/backtest_trades.csv")
        write_metrics_json(metrics, "reports/backtest_metrics.json")

    async def _run_paper(self) -> None:
        setup_logging(self._cfg.logging.level)
        log = get_logger("paper")

        cfg = self._cfg
        fees = FeesSnapshot(
            maker_fee_rate=cfg.fees.maker_fee_rate,
            taker_fee_rate=cfg.fees.taker_fee_rate,
            slippage_bps=cfg.fees.slippage_bps,
            funding_rate=None,
        )
        strategy = build_strategy(cfg.strategy)
        risk = RiskManager(
            portfolio_limits=PortfolioLimits(
                max_total_positions=cfg.risk.max_total_positions,
                max_total_notional_usdt=cfg.risk.max_total_notional_usdt,
                daily_loss_limit_usdt=cfg.risk.daily_loss_limit_usdt,
            ),
            symbol_limits=SymbolLimits(min_liquidation_distance_pct=cfg.risk.min_liquidation_distance_pct),
            loss_streak=LossStreakGuard(limit=cfg.risk.loss_streak_limit),
            ladder_limits=None,
            kill_switch=KillSwitch(),
        )

        # Minimal "universe" for paper: use 1 symbol but go through same selector code.
        btc = SymbolMeta(
            symbol="BTCUSDT",
            status="TRADING",
            base_asset="BTC",
            quote_asset="USDT",
            price_precision=2,
            quantity_precision=6,
            tick_size=0.1,
            step_size=0.0001,
            min_qty=0.0001,
            min_notional=5.0,
        )
        sim = SimulatorExchange(
            cfg=cfg.exchange,
            symbol_meta={"BTCUSDT": btc},
            maker_fee_rate=cfg.fees.maker_fee_rate,
            taker_fee_rate=cfg.fees.taker_fee_rate,
            slippage_bps=cfg.fees.slippage_bps,
            spread_bps=float(cfg.exchange.sim_spread_bps),
            partial_fill_pct=float(cfg.exchange.sim_partial_fill_pct),
            initial_usdt=1000.0,
        )
        selector = UniverseSelector(cfg.universe)
        registry = await selector.refresh(sim)
        symbols = registry.symbols

        router = OrderRouter(registry.symbol_meta)
        state = AccountState()
        om = OrderManager(exchange=sim, router=router, state=state, storage=None)

        indicators = build_indicators(cfg.strategy.indicators)
        history: dict[str, list[Candle]] = {s: [] for s in symbols}
        trade_store = TradeStore("data/trades.sqlite3")
        trade_store.init_schema()
        open_trade_id_by_symbol: dict[str, str] = {}
        open_trade_pnl_by_symbol: dict[str, float] = {}

        def _apply_sizing(intent: Intent, *, last_price: float, ind_results: dict[str, Any], state: AccountState) -> Intent:
            sizing_cfg = cfg.strategy.sizing or {}
            kind = str(sizing_cfg.get("kind", "fixed_notional"))
            if kind == "fixed_risk":
                sl_pct = float(intent.meta.get("sl_pct", 0.0)) if intent.meta else 0.0
                if sl_pct <= 0:
                    sl_pct = float(((cfg.strategy.exits or {}).get("tp_sl") or {}).get("stop_loss_pct", 0.0))
                equity = float(state.balances.get("USDT").total) if state.balances.get("USDT") else 0.0
                fr = FixedRiskSizing(
                    risk_pct=float(sizing_cfg.get("risk_pct", 0.5)),
                    max_notional_usdt=float(sizing_cfg.get("max_notional_usdt")) if "max_notional_usdt" in sizing_cfg else None,
                    min_notional_usdt=float(sizing_cfg.get("min_notional_usdt")) if "min_notional_usdt" in sizing_cfg else None,
                )
                notional = fr.compute_notional(equity_usdt=equity, stop_loss_pct=sl_pct)
                if notional:
                    return Intent(
                        symbol=intent.symbol,
                        position_side=intent.position_side,
                        action=intent.action,
                        notional_usdt=float(notional),
                        signal=intent.signal,
                        prefer_maker=intent.prefer_maker,
                        max_slippage_bps=intent.max_slippage_bps,
                        meta=intent.meta,
                    )
            if kind == "volatility_adjusted":
                atr_res = ind_results.get("atr")
                atr = float(atr_res.values.get("atr")) if atr_res and atr_res.is_ready else 0.0
                va = VolatilityAdjustedSizing(
                    base_notional_usdt=float(sizing_cfg.get("base_notional_usdt", sizing_cfg.get("notional_usdt", 100.0))),
                    atr_target_pct=float(sizing_cfg.get("atr_target_pct", 1.0)),
                    min_notional_usdt=float(sizing_cfg.get("min_notional_usdt")) if "min_notional_usdt" in sizing_cfg else None,
                    max_notional_usdt=float(sizing_cfg.get("max_notional_usdt")) if "max_notional_usdt" in sizing_cfg else None,
                )
                notional = va.compute_notional(atr=atr, price=last_price)
                if notional:
                    return Intent(
                        symbol=intent.symbol,
                        position_side=intent.position_side,
                        action=intent.action,
                        notional_usdt=float(notional),
                        signal=intent.signal,
                        prefer_maker=intent.prefer_maker,
                        max_slippage_bps=intent.max_slippage_bps,
                        meta=intent.meta,
                    )
            return intent

        fixture_csv = Path("tests/fixtures/sample_candles.csv")
        rows = list(csv.DictReader(fixture_csv.open("r")))
        for row in rows:
            # replay same candles for all symbols in paper mode
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            for sym in symbols:
                candle = Candle(
                    symbol=sym,
                    timeframe=cfg.market_data.timeframe,
                    open_time=ts,
                    close_time=ts + timedelta(minutes=1),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
                sim.update_mark_price(sym, candle.close)
                history[sym].append(candle)
                ind_results = {name: ind.compute(history[sym]) for name, ind in indicators.items()}
                # keep local state in-sync from the simulator snapshot (for close detection)
                state.set_positions(await sim.fetch_positions())
                state.set_balances(await sim.fetch_balances())

                ctx = StrategyContext(
                    mode="paper",
                    symbol=sym,
                    timeframe=candle.timeframe,
                    indicators=ind_results,
                    fees=fees,
                    positions={},
                    balances={},
                )
                intents = strategy.on_candle(candle, ctx)
                for intent in intents:
                    intent = _apply_sizing(intent, last_price=candle.close, ind_results=ind_results, state=state)
                    dec = risk.validate_intent(intent, state=state, fees=fees, last_price=candle.close)
                    if not dec.allowed:
                        log.debug("Intent blocked: %s %s", dec.blocked_by, dec.reason)
                        continue
                    # Open trade record on first allowed OPEN for a symbol without an open trade record.
                    if intent.action == "OPEN" and sym not in open_trade_id_by_symbol:
                        tid = uuid.uuid4().hex[:12]
                        rh = rules_hash((intent.meta or {}).get("rules") or {"intent_signal": intent.signal.value})
                        trade_store.open_trade(
                            trade_id=tid,
                            mode="paper",
                            symbol=sym,
                            timeframe=candle.timeframe,
                            direction=intent.position_side.value,
                            rules_hash=rh,
                            entry_time=candle.close_time,
                            rules=(intent.meta or {}).get("rules"),
                            indicators_snapshot=(intent.meta or {}).get("indicators_snapshot"),
                            meta={"source": "paper", "signal": intent.signal.value, "entry_candle": (intent.meta or {}).get("entry_candle")},
                        )
                        open_trade_id_by_symbol[sym] = tid
                        open_trade_pnl_by_symbol[sym] = 0.0
                    order = await om.submit_intent(intent, last_price=candle.close)
                    fill = order.meta.get("fill") if order.meta else None
                    if fill is not None:
                        risk.loss_streak.on_fill(fill)
                        # Track realized pnl for the currently open trade for this symbol
                        if sym in open_trade_pnl_by_symbol and fill.realized_pnl is not None:
                            open_trade_pnl_by_symbol[sym] += float(fill.realized_pnl)
                    log.info("Paper fill: %s %s %s qty=%s price=%s", sym, intent.signal.value, intent.position_side.value, order.executed_qty, order.price)
                # Close trade if simulator position is now closed
                state.set_positions(await sim.fetch_positions())
                still_open = any(p.symbol == sym for p in state.positions.values())
                if (not still_open) and sym in open_trade_id_by_symbol:
                    tid = open_trade_id_by_symbol.pop(sym)
                    pnl = float(open_trade_pnl_by_symbol.pop(sym, 0.0))
                    trade_store.close_trade(trade_id=tid, exit_time=candle.close_time, realized_pnl_usdt=pnl)

        log.info("Paper finished. RealizedPnL=%s FeesPaid=%s", state.realized_pnl_usdt, state.fees_paid_usdt)

    async def _run_live(self) -> None:
        cfg = self._cfg
        setup_logging(cfg.logging.level)
        log = get_logger("live")

        env_live = os.environ.get("LIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
        if not (env_live and cfg.risk.live_enabled):
            raise RuntimeError(
                "Live is disabled. Set LIVE_ENABLED=true in .env and risk.live_enabled=true in config."
            )

        keys = load_keys_from_env()
        exchange = BinanceFuturesUsdtmClient(cfg=cfg.exchange, keys=keys, limiter=SimpleRateLimiter(max_per_sec=5))

        user_stream: UserStreamClient | None = None
        keepalive_task: asyncio.Task[None] | None = None
        decision_store = DecisionStore("data/decisions.sqlite3")
        decision_store.init_schema()
        fill_store = FillStore("data/fills.sqlite3")
        fill_store.init_schema()
        trade_store = TradeStore("data/trades.sqlite3")
        trade_store.init_schema()
        open_trade_id_by_symbol: dict[str, str] = {}
        open_trade_pnl_by_symbol: dict[str, float] = {}
        try:
            selector = UniverseSelector(cfg.universe)
            registry = await selector.refresh(exchange)
            if not registry.symbols:
                raise RuntimeError("Universe is empty after filters/config.")
            symbols = registry.symbols
            log.info("Live universe: %s", symbols)

            state = AccountState()
            # initial sync
            state.set_positions(await exchange.fetch_positions())
            state.set_balances(await exchange.fetch_balances())

            async def _handle_user_event(msg: dict[str, Any]) -> None:
                etype = msg.get("e")
                if etype == "ACCOUNT_UPDATE":
                    acc = msg.get("a", {}) or {}
                    balances: list[Balance] = []
                    positions = []
                    event_time = msg.get("E")
                    update_time = datetime.fromtimestamp(event_time / 1000.0, tz=timezone.utc) if event_time else datetime.now(timezone.utc)
                    for b in acc.get("B", []) or []:
                        asset = b.get("a", "")
                        if not asset:
                            continue
                        wallet = float(b.get("wb", 0.0))
                        available = float(b.get("cw", wallet))
                        balances.append(Balance(asset=asset, available=available, total=wallet, update_time=update_time))
                    for p in acc.get("P", []) or []:
                        qty = float(p.get("pa", 0.0))
                        if abs(qty) < 1e-9:
                            continue
                        ps = p.get("ps")
                        if ps == "LONG":
                            position_side = PositionSide.LONG
                        elif ps == "SHORT":
                            position_side = PositionSide.SHORT
                        else:
                            position_side = PositionSide.LONG if qty > 0 else PositionSide.SHORT
                        positions.append(
                            Position(
                                symbol=p.get("s", ""),
                                position_side=position_side,
                                quantity=abs(qty),
                                entry_price=float(p.get("ep", 0.0)),
                                mark_price=float(p.get("mp", 0.0)) if p.get("mp") is not None else None,
                                unrealized_pnl=float(p.get("up", 0.0)) if p.get("up") is not None else None,
                                leverage=int(float(p.get("l", 0) or 0)) or None,
                                liquidation_price=float(p.get("lp", 0.0)) if p.get("lp") else None,
                                update_time=update_time,
                            )
                        )
                    if balances:
                        state.set_balances(balances)
                    if positions:
                        state.set_positions(positions)
                    return

                if etype == "ORDER_TRADE_UPDATE":
                    o = msg.get("o", {}) or {}
                    status_str = o.get("X", "")
                    status = {
                        "NEW": OrderStatus.NEW,
                        "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
                        "FILLED": OrderStatus.FILLED,
                        "CANCELED": OrderStatus.CANCELED,
                        "REJECTED": OrderStatus.REJECTED,
                        "EXPIRED": OrderStatus.EXPIRED,
                    }.get(status_str, OrderStatus.NEW)
                    order_type_str = o.get("o", "MARKET")
                    try:
                        order_type = OrderType(order_type_str)
                    except Exception:
                        order_type = OrderType.MARKET
                    price = float(o.get("p", 0.0))
                    if price <= 0 and o.get("ap") is not None:
                        price = float(o.get("ap") or 0.0)
                    order = Order(
                        order_id=str(o.get("i", "")),
                        client_order_id=o.get("c"),
                        symbol=o.get("s", ""),
                        side=Side(o.get("S")),
                        order_type=order_type,
                        status=status,
                        price=price if price > 0 else None,
                        orig_qty=float(o.get("q", 0.0)),
                        executed_qty=float(o.get("z", 0.0)),
                        update_time=datetime.fromtimestamp((o.get("T") or msg.get("E") or 0) / 1000.0, tz=timezone.utc),
                        reduce_only=bool(o.get("R", False) or o.get("reduceOnly", False)),
                        meta={"event": msg},
                    )
                    state.apply_order_update(order)

                    last_qty = float(o.get("l", 0.0))
                    if last_qty > 0:
                        fill = Fill(
                            symbol=o.get("s", ""),
                            order_id=str(o.get("i", "")),
                            trade_id=str(o.get("t", "")),
                            side=Side(o.get("S")),
                            price=float(o.get("L", 0.0)),
                            quantity=last_qty,
                            fee_asset=o.get("N") or "",
                            fee_paid=float(o.get("n", 0.0)),
                            realized_pnl=float(o.get("rp", 0.0)) if o.get("rp") is not None else None,
                            time=datetime.fromtimestamp((o.get("T") or msg.get("E") or 0) / 1000.0, tz=timezone.utc),
                            meta={"event": msg},
                        )
                        state.apply_fill(fill)
                        risk.loss_streak.on_fill(fill)
                        if fill.symbol in open_trade_pnl_by_symbol and fill.realized_pnl is not None:
                            open_trade_pnl_by_symbol[fill.symbol] += float(fill.realized_pnl)
                        fill_store.record(
                            FillRecord(
                                time=fill.time,
                                symbol=fill.symbol,
                                side=fill.side.value,
                                price=float(fill.price),
                                quantity=float(fill.quantity),
                                fee_asset=fill.fee_asset,
                                fee_paid=float(fill.fee_paid),
                                realized_pnl=fill.realized_pnl,
                                order_id=fill.order_id,
                                trade_id=fill.trade_id,
                                meta={"event": msg},
                            )
                        )
                    return

            # Start user data stream (futures)
            try:
                listen_key = await exchange.start_user_stream()
                user_stream = UserStreamClient(WsConfig(ws_base_url=cfg.exchange.ws_base_url), listen_key, _handle_user_event)
                await user_stream.start()
                log.info("User stream started.")

                async def _keepalive_loop() -> None:
                    while True:
                        await asyncio.sleep(30 * 60)
                        try:
                            await exchange.keepalive_user_stream(listen_key)
                        except Exception as e:
                            log.warning("User stream keepalive failed: %s", e)

                keepalive_task = asyncio.create_task(_keepalive_loop())
            except Exception as e:
                log.warning("User stream disabled (failed to start): %s", e)

            router = OrderRouter(registry.symbol_meta)
            om = OrderManager(exchange=exchange, router=router, state=state, storage=None)

            fees = FeesSnapshot(
                maker_fee_rate=cfg.fees.maker_fee_rate,
                taker_fee_rate=cfg.fees.taker_fee_rate,
                slippage_bps=cfg.fees.slippage_bps,
                funding_rate=None,
            )
            strategy = build_strategy(cfg.strategy)
            # DEBUG: Log strategy config to trace TP/SL values
            strat_name = cfg.strategy.name
            strat_signals = cfg.strategy.signals or {}
            strat_params = strat_signals.get(strat_name, {}) if strat_signals else {}
            log.info(
                "Strategy DEBUG: name=%s signals_keys=%s %s_params=%s",
                strat_name,
                list(strat_signals.keys()),
                strat_name,
                {k: strat_params.get(k) for k in ["tp_usdt", "sl_usdt", "tp_atr_mult", "sl_atr_mult", "ignore_fees_gate"]},
            )
            # Also log the strategy object's actual values
            if hasattr(strategy, "tp_usdt") or hasattr(strategy, "sl_usdt"):
                log.info(
                    "Strategy INSTANCE DEBUG: tp_usdt=%s sl_usdt=%s tp_atr_mult=%s sl_atr_mult=%s",
                    getattr(strategy, "tp_usdt", None),
                    getattr(strategy, "sl_usdt", None),
                    getattr(strategy, "tp_atr_mult", None),
                    getattr(strategy, "sl_atr_mult", None),
                )
            # Log the actual rules that will be evaluated
            if hasattr(strategy, "rules"):
                log.info(
                    "Strategy RULES DEBUG: %s",
                    [r.get("type") if isinstance(r, dict) else str(r) for r in getattr(strategy, "rules", [])],
                )
            demo_mode = isinstance(strategy, DemoImmediateLongStrategy)
            scanner_cfg = (cfg.strategy.signals or {}).get("scanner", {})
            scanner_enabled = bool(scanner_cfg.get("enabled", False))
            indicators = build_indicators(cfg.strategy.indicators)
            history: dict[str, list[Candle]] = {s: [] for s in symbols}
            open_candles: dict[str, int] = {}  # symbol -> candles since entry
            demo_opened: set[str] = set()
            had_position: set[str] = set()
            bracket_meta_by_symbol: dict[str, dict[str, Any]] = {}

            risk = RiskManager(
                portfolio_limits=PortfolioLimits(
                    max_total_positions=cfg.risk.max_total_positions,
                    max_total_notional_usdt=cfg.risk.max_total_notional_usdt,
                    daily_loss_limit_usdt=cfg.risk.daily_loss_limit_usdt,
                ),
                symbol_limits=SymbolLimits(min_liquidation_distance_pct=cfg.risk.min_liquidation_distance_pct),
                loss_streak=LossStreakGuard(limit=cfg.risk.loss_streak_limit),
                ladder_limits=None,
                kill_switch=KillSwitch(),
            )

            bracket_manager = BracketManager(
                exchange=exchange,
                symbol_meta=registry.symbol_meta,
                tp_kind=str(scanner_cfg.get("tp_order_kind", "limit")).strip().lower(),
                sl_kind=str(scanner_cfg.get("sl_order_kind", "market")).strip().lower(),
                limit_offset_ticks=int(scanner_cfg.get("limit_offset_ticks", 0)),
            )

            def _apply_sizing(intent: Intent, *, last_price: float, ind_results: dict[str, Any]) -> Intent:
                sizing_cfg = cfg.strategy.sizing or {}
                kind = str(sizing_cfg.get("kind", "fixed_notional"))
                if kind == "fixed_risk":
                    sl_pct = float(intent.meta.get("sl_pct", 0.0)) if intent.meta else 0.0
                    if sl_pct <= 0:
                        sl_pct = float(((cfg.strategy.exits or {}).get("tp_sl") or {}).get("stop_loss_pct", 0.0))
                    equity = float(state.balances.get("USDT").total) if state.balances.get("USDT") else 0.0
                    fr = FixedRiskSizing(
                        risk_pct=float(sizing_cfg.get("risk_pct", 0.5)),
                        max_notional_usdt=float(sizing_cfg.get("max_notional_usdt")) if "max_notional_usdt" in sizing_cfg else None,
                        min_notional_usdt=float(sizing_cfg.get("min_notional_usdt")) if "min_notional_usdt" in sizing_cfg else None,
                    )
                    notional = fr.compute_notional(equity_usdt=equity, stop_loss_pct=sl_pct)
                    if notional:
                        return Intent(
                            symbol=intent.symbol,
                            position_side=intent.position_side,
                            action=intent.action,
                            notional_usdt=float(notional),
                            signal=intent.signal,
                            prefer_maker=intent.prefer_maker,
                            max_slippage_bps=intent.max_slippage_bps,
                            meta=intent.meta,
                        )
                if kind == "volatility_adjusted":
                    atr_res = ind_results.get("atr")
                    atr = float(atr_res.values.get("atr")) if atr_res and atr_res.is_ready else 0.0
                    va = VolatilityAdjustedSizing(
                        base_notional_usdt=float(sizing_cfg.get("base_notional_usdt", sizing_cfg.get("notional_usdt", 100.0))),
                        atr_target_pct=float(sizing_cfg.get("atr_target_pct", 1.0)),
                        min_notional_usdt=float(sizing_cfg.get("min_notional_usdt")) if "min_notional_usdt" in sizing_cfg else None,
                        max_notional_usdt=float(sizing_cfg.get("max_notional_usdt")) if "max_notional_usdt" in sizing_cfg else None,
                    )
                    notional = va.compute_notional(atr=atr, price=last_price)
                    if notional:
                        return Intent(
                            symbol=intent.symbol,
                            position_side=intent.position_side,
                            action=intent.action,
                            notional_usdt=float(notional),
                            signal=intent.signal,
                            prefer_maker=intent.prefer_maker,
                            max_slippage_bps=intent.max_slippage_bps,
                            meta=intent.meta,
                        )
                return intent

            def _ensure_exit_meta(intent: Intent) -> Intent:
                """
                Ensure intent meta contains TP/SL values if strategy config defines them.
                This is a safety net for scanner runs where the strategy didn't attach exits.
                """
                meta = dict(intent.meta or {})
                tp_pct = float(meta.get("tp_pct", 0.0) or 0.0)
                sl_pct = float(meta.get("sl_pct", 0.0) or 0.0)
                tp_usdt = float(meta.get("tp_usdt", 0.0) or 0.0)
                sl_usdt = float(meta.get("sl_usdt", 0.0) or 0.0)

                if tp_pct <= 0 and sl_pct <= 0 and tp_usdt <= 0 and sl_usdt <= 0:
                    signals = cfg.strategy.signals or {}
                    rule_combo = signals.get("rule_combo") or {}
                    tp_usdt_default = float(rule_combo.get("tp_usdt", 0.0) or 0.0)
                    sl_usdt_default = float(rule_combo.get("sl_usdt", 0.0) or 0.0)
                    if tp_usdt_default > 0:
                        meta["tp_usdt"] = tp_usdt_default
                    if sl_usdt_default > 0:
                        meta["sl_usdt"] = sl_usdt_default

                    # As a final fallback, use pct exits if configured in strategy.exits.tp_sl
                    if (float(meta.get("tp_usdt", 0.0) or 0.0) <= 0) and (float(meta.get("sl_usdt", 0.0) or 0.0) <= 0):
                        exits = (cfg.strategy.exits or {}).get("tp_sl") or {}
                        tp_pct_default = float(exits.get("take_profit_pct", 0.0) or 0.0)
                        sl_pct_default = float(exits.get("stop_loss_pct", 0.0) or 0.0)
                        if tp_pct_default > 0:
                            meta["tp_pct"] = tp_pct_default
                        if sl_pct_default > 0:
                            meta["sl_pct"] = sl_pct_default

                if meta != (intent.meta or {}):
                    return Intent(
                        symbol=intent.symbol,
                        position_side=intent.position_side,
                        action=intent.action,
                        notional_usdt=float(intent.notional_usdt),
                        signal=intent.signal,
                        prefer_maker=intent.prefer_maker,
                        max_slippage_bps=intent.max_slippage_bps,
                        meta=meta,
                    )
                return intent

            async def _place_brackets_after_open(
                sym: str,
                intent: Intent,
                *,
                qty_hint: float | None = None,
                entry_price_hint: float | None = None,
            ) -> None:
                print(f"[PRINT] _place_brackets_after_open ENTRY for {sym}", flush=True)
                # NOTE:
                # Binance can lag / occasionally hang on positionRisk right after entry. We must not block bracket placement
                # on fetch_positions(). Prefer using order execution hints if position is not visible quickly.
                pos: Position | None = None
                tp_pct0 = float(intent.meta.get("tp_pct", 0.0)) if intent.meta else 0.0
                sl_pct0 = float(intent.meta.get("sl_pct", 0.0)) if intent.meta else 0.0
                tp_usdt0 = float(intent.meta.get("tp_usdt", 0.0)) if intent.meta else 0.0
                sl_usdt0 = float(intent.meta.get("sl_usdt", 0.0)) if intent.meta else 0.0
                print(f"[PRINT] tp_pct={tp_pct0} sl_pct={sl_pct0} tp_usdt={tp_usdt0} sl_usdt={sl_usdt0}", flush=True)
                log.info(
                    "Bracket placement begin for %s (tp_pct=%.4f sl_pct=%.4f tp_usdt=%.4f sl_usdt=%.4f qty_hint=%s entry_hint=%s)",
                    sym,
                    tp_pct0,
                    sl_pct0,
                    tp_usdt0,
                    sl_usdt0,
                    float(qty_hint or 0.0),
                    float(entry_price_hint or 0.0),
                )

                # Try to fetch the true position quickly (best accuracy), but never block for long.
                for _ in range(6):  # up to ~3s total
                    try:
                        positions = await asyncio.wait_for(exchange.fetch_positions(), timeout=2.0)
                    except Exception as e:
                        log.warning("Bracket placement: fetch_positions failed for %s: %s", sym, e)
                        break
                    pos = next((p for p in positions if p.symbol == sym), None)
                    if pos is not None and pos.quantity > 0:
                        break
                    await asyncio.sleep(0.5)
                if pos is None or pos.quantity <= 0:
                    qh = float(qty_hint or 0.0)
                    eph = float(entry_price_hint or 0.0)
                    if qh > 0 and eph > 0:
                        qty = qh
                        entry_price = eph
                        position_side = intent.position_side
                        log.warning(
                            "Bracket placement: position not visible yet for %s; using order hints qty=%.8f entry=%.8f",
                            sym,
                            qty,
                            entry_price,
                        )
                    else:
                        log.warning("Bracket placement delayed/failed: no position found for %s after retry window", sym)
                        return
                else:
                    qty = float(pos.quantity)
                    entry_price = float(pos.entry_price)
                    position_side = pos.position_side
                tp_pct = float(intent.meta.get("tp_pct", 0.0)) if intent.meta else 0.0
                sl_pct = float(intent.meta.get("sl_pct", 0.0)) if intent.meta else 0.0
                tp_usdt = float(intent.meta.get("tp_usdt", 0.0)) if intent.meta else 0.0
                sl_usdt = float(intent.meta.get("sl_usdt", 0.0)) if intent.meta else 0.0
                tp_levels = intent.meta.get("tp_levels") if intent.meta else None

                if qty <= 0:
                    log.warning("Bracket placement skipped: qty<=0 for %s", sym)
                    return
                if (tp_levels is None) and (tp_pct <= 0 and sl_pct <= 0) and (tp_usdt <= 0 and sl_usdt <= 0):
                    log.warning(
                        "Bracket placement skipped: no exits configured for %s (tp_pct=%.4f sl_pct=%.4f tp_usdt=%.4f sl_usdt=%.4f)",
                        sym,
                        tp_pct,
                        sl_pct,
                        tp_usdt,
                        sl_usdt,
                    )
                    return

                log.info(
                    "Placing brackets for %s qty=%.8f entry=%.8f (tp_pct=%.4f sl_pct=%.4f tp_usdt=%.4f sl_usdt=%.4f)",
                    sym,
                    qty,
                    entry_price,
                    tp_pct,
                    sl_pct,
                    tp_usdt,
                    sl_usdt,
                )
                try:
                    print(f"[PRINT] calling bracket_manager.place_for_position for {sym} qty={qty} entry={entry_price} tp_pct={tp_pct} sl_pct={sl_pct} tp_usdt={tp_usdt} sl_usdt={sl_usdt}", flush=True)
                    orders = await bracket_manager.place_for_position(
                        symbol=sym,
                        position_side=position_side,
                        qty=qty,
                        entry_price=entry_price,
                        tp_pct=tp_pct,
                        sl_pct=sl_pct,
                        tp_usdt=tp_usdt,
                        sl_usdt=sl_usdt,
                        tp_levels=tp_levels if isinstance(tp_levels, list) else None,
                    )
                    print(f"[PRINT] bracket_manager.place_for_position DONE: tp_id={orders.tp_order_id} sl_id={orders.sl_order_id}", flush=True)
                    tp_required = bool(tp_levels) or (tp_pct > 0) or (tp_usdt > 0)
                    sl_required = (sl_pct > 0) or (sl_usdt > 0)
                    if tp_required and not orders.tp_order_id:
                        print(f"[PRINT] WARNING: TP NOT placed for {sym}", flush=True)
                    if sl_required and not orders.sl_order_id:
                        print(f"[PRINT] WARNING: SL NOT placed for {sym}", flush=True)
                except Exception as e:
                    print(f"[PRINT] bracket_manager.place_for_position FAILED: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    return

                tstop = int(intent.meta.get("time_stop_candles", 0)) if intent.meta else 0
                if tstop > 0:
                    open_candles[sym] = 0
                    log.info("Time-stop enabled: %s candles", tstop)

            # Scanner: pick ONE symbol immediately using historical candles (no warmup waiting)
            if scanner_enabled and (not demo_mode):
                loss_streak_cooldown_sec = float(scanner_cfg.get("loss_streak_cooldown_sec", cfg.risk.loss_streak_cooldown_sec) or 0.0)
                loss_streak_cooldown_until: datetime | None = None

                scan_limit = int(scanner_cfg.get("history_limit", 300))
                entry_timeframe = str(scanner_cfg.get("entry_timeframe", cfg.market_data.timeframe))
                entry_lookback = int(scanner_cfg.get("entry_lookback", 0)) or scan_limit
                confirm_timeframes = scanner_cfg.get("confirm_timeframes", []) or []
                if not isinstance(confirm_timeframes, list):
                    confirm_timeframes = [confirm_timeframes]
                confirm_timeframes = [str(x) for x in confirm_timeframes if x]
                confirm_history_limit = int(scanner_cfg.get("confirm_history_limit", 200))

                entry_indicator_cfg = scanner_cfg.get("entry_indicators") or cfg.strategy.indicators
                confirm_indicator_cfg = scanner_cfg.get("confirm_indicators") or cfg.strategy.indicators
                scanner_entry_indicators = build_indicators(entry_indicator_cfg)
                scanner_confirm_indicators = build_indicators(confirm_indicator_cfg)
                log.info(
                    "Scanner DEBUG: entry_indicators=%s confirm_indicators=%s strategy=%s",
                    list(scanner_entry_indicators.keys()),
                    list(scanner_confirm_indicators.keys()),
                    type(strategy).__name__,
                )

                exit_after_entry = bool(scanner_cfg.get("exit_after_entry", True))
                exit_on_close = bool(scanner_cfg.get("exit_on_close", False))
                rounds = int(scanner_cfg.get("rounds", 1))
                avoid_consecutive = bool(scanner_cfg.get("avoid_consecutive_symbol", rounds > 1))
                avoid_repeat_within_run = bool(scanner_cfg.get("avoid_repeat_within_run", False))
                sleep_between_rounds = float(scanner_cfg.get("sleep_between_rounds_sec", 2.0))
                retry_on_no_match = bool(scanner_cfg.get("retry_on_no_match", rounds > 1))
                retry_sleep_sec = float(scanner_cfg.get("retry_sleep_sec", 30.0))
                risk_scope = str(scanner_cfg.get("risk_scope", "account")).strip().lower()  # "account" | "bot"
                exclude_symbols_with_open_positions = bool(scanner_cfg.get("exclude_symbols_with_open_positions", True))

                universe_symbols = list(symbols)
                universe_meta = dict(registry.symbol_meta)

                # If you (the human) already have manual positions open, never touch those symbols.
                # This prevents the bot from modifying/closing your manual position (one-way mode netting).
                initial_positions = await exchange.fetch_positions()
                locked_symbols = {p.symbol for p in initial_positions}
                if locked_symbols:
                    log.info("Scanner locked symbols (existing open positions): %s", sorted(locked_symbols))

                # Track bot-managed active symbols so portfolio limits can be applied to the bot only (optional).
                bot_active_symbols: set[str] = set()
                traded_symbols: set[str] = set()

                async def _cleanup_symbol(sym: str) -> None:
                    await bracket_manager.cleanup(sym)

                def _with_meta(intent: Intent, meta_patch: dict[str, Any]) -> Intent:
                    meta = dict(intent.meta or {})
                    meta.update(meta_patch or {})
                    return Intent(
                        symbol=intent.symbol,
                        position_side=intent.position_side,
                        action=intent.action,
                        notional_usdt=float(intent.notional_usdt),
                        signal=intent.signal,
                        prefer_maker=intent.prefer_maker,
                        max_slippage_bps=intent.max_slippage_bps,
                        meta=meta,
                    )

                def _apply_atr_exits(intent: Intent, ind_results: dict[str, Any], *, price: float) -> Intent:
                    """
                    If meta contains tp_atr_mult/sl_atr_mult, compute tp_pct/sl_pct from ATR and attach to meta.
                    This is used to make exits adapt to volatility (anti-whipsaw), without changing entry rules.
                    """
                    meta = dict(intent.meta or {})
                    tp_mult = float(meta.get("tp_atr_mult", 0.0) or 0.0)
                    sl_mult = float(meta.get("sl_atr_mult", 0.0) or 0.0)
                    if tp_mult <= 0 and sl_mult <= 0:
                        return intent
                    atr_res = ind_results.get("atr")
                    if not atr_res or not getattr(atr_res, "is_ready", False):
                        return intent
                    atr_v = float(getattr(atr_res, "values", {}).get("atr") or 0.0)
                    if price <= 0 or atr_v <= 0:
                        return intent
                    patch: dict[str, Any] = {}
                    if tp_mult > 0:
                        patch["tp_pct"] = (atr_v * tp_mult / price) * 100.0
                    if sl_mult > 0:
                        patch["sl_pct"] = (atr_v * sl_mult / price) * 100.0
                    return _with_meta(intent, patch)

                async def _manage_open_position(
                    *,
                    sym: str,
                    pos: Position,
                    meta: dict[str, Any],
                    entry_time_iso: str | None,
                    entry_timeframe: str,
                    om: OrderManager,
                ) -> None:
                    # break-even + trailing while scanner waits (scanner loop doesn't stream candles)
                    entry_price = float(meta.get("entry_price") or pos.entry_price)
                    px = float(pos.mark_price or 0.0)
                    if entry_price <= 0 or px <= 0:
                        return

                    trailing_pct = float(meta.get("trailing_stop_pct", 0.0) or 0.0)
                    break_even_pct = float(meta.get("break_even_pct", 0.0) or 0.0)
                    break_even_done = bool(meta.get("break_even_done", False))

                    if break_even_pct > 0 and not break_even_done:
                        if pos.position_side == PositionSide.LONG and px >= entry_price * (1.0 + break_even_pct / 100.0):
                            await bracket_manager.replace_sl_at_price(
                                symbol=sym,
                                position_side=pos.position_side,
                                qty=float(pos.quantity),
                                stop_price=entry_price,
                            )
                            meta["break_even_done"] = True
                        elif pos.position_side == PositionSide.SHORT and px <= entry_price * (1.0 - break_even_pct / 100.0):
                            await bracket_manager.replace_sl_at_price(
                                symbol=sym,
                                position_side=pos.position_side,
                                qty=float(pos.quantity),
                                stop_price=entry_price,
                            )
                            meta["break_even_done"] = True

                    if trailing_pct > 0:
                        if pos.position_side == PositionSide.LONG:
                            meta["trail_high"] = max(float(meta.get("trail_high", px)), px)
                            trail_price = float(meta["trail_high"]) * (1.0 - trailing_pct / 100.0)
                        else:
                            meta["trail_low"] = min(float(meta.get("trail_low", px)), px)
                            trail_price = float(meta["trail_low"]) * (1.0 + trailing_pct / 100.0)
                        last_trail = float(meta.get("last_trail_price", 0.0) or 0.0)
                        if abs(trail_price - last_trail) > 0:
                            await bracket_manager.replace_sl_at_price(
                                symbol=sym,
                                position_side=pos.position_side,
                                qty=float(pos.quantity),
                                stop_price=trail_price,
                            )
                            meta["last_trail_price"] = trail_price

                    # time-stop (candles) for scanner
                    tstop_candles = int(meta.get("time_stop_candles", 0) or 0)
                    if tstop_candles > 0 and entry_time_iso and not meta.get("time_stop_submitted"):
                        step = TIMEFRAME_TO_SECONDS.get(entry_timeframe)
                        if step:
                            entry_time = datetime.fromisoformat(entry_time_iso)
                            age = (datetime.now(timezone.utc) - entry_time).total_seconds()
                            if age >= float(tstop_candles * step):
                                notional = float(pos.quantity) * float(pos.mark_price or entry_price)
                                close_intent = Intent(
                                    symbol=sym,
                                    position_side=pos.position_side,
                                    action="CLOSE",
                                    notional_usdt=notional,
                                    signal=(Signal.SELL if pos.position_side == PositionSide.LONG else Signal.BUY),
                                    meta={"time_stop": True},
                                )
                                await om.submit_intent(close_intent, last_price=float(pos.mark_price or entry_price))
                                meta["time_stop_submitted"] = True

                async def _pick_symbol(last_sym: str | None) -> tuple[str, Intent] | None:
                    best: tuple[float, str, Intent] | None = None
                    # Also avoid any symbol that currently has an open position (manual or bot).
                    current_open_symbols: set[str] = set()
                    if exclude_symbols_with_open_positions:
                        try:
                            current_open_symbols = {p.symbol for p in (await exchange.fetch_positions())}
                        except Exception as e:
                            log.warning("Scanner: failed fetching current positions for exclusion: %s", e)
                    for sym in universe_symbols:
                        if avoid_consecutive and last_sym is not None and sym == last_sym:
                            continue
                        if avoid_repeat_within_run and sym in traded_symbols:
                            continue
                        if sym in locked_symbols:
                            continue
                        if exclude_symbols_with_open_positions and sym in current_open_symbols:
                            continue
                        try:
                            # ENTRY timeframe: use last N candles (e.g., 15 x 1m) for the actual trigger
                            klines = await exchange.fetch_klines(sym, entry_timeframe, limit=int(entry_lookback))
                        except Exception as e:
                            log.warning("Scanner: failed fetching klines for %s: %s", sym, e)
                            continue
                        entry_candles = klines_to_candles(sym, entry_timeframe, klines)
                        if len(entry_candles) < int(entry_lookback):
                            continue
                        entry_ind_results = {name: ind.compute(entry_candles) for name, ind in scanner_entry_indicators.items()}
                        ctx_entry = StrategyContext(
                            mode="live",
                            symbol=sym,
                            timeframe=entry_timeframe,
                            indicators=entry_ind_results,
                            fees=fees,
                            positions={},
                            balances={},
                        )
                        intents = strategy.on_candle(entry_candles[-1], ctx_entry)
                        if not intents:
                            continue
                        it = _apply_atr_exits(intents[0], entry_ind_results, price=float(entry_candles[-1].close))
                        # CONFIRM timeframes: require same-direction signal on each higher timeframe
                        ok = True
                        for tf in confirm_timeframes:
                            try:
                                k2 = await exchange.fetch_klines(sym, tf, limit=int(confirm_history_limit))
                            except Exception as e:
                                log.warning("Scanner: failed fetching confirm klines for %s %s: %s", sym, tf, e)
                                ok = False
                                break
                            c2 = klines_to_candles(sym, tf, k2)
                            if len(c2) < 60:
                                ok = False
                                break
                            ind2 = {name: ind.compute(c2) for name, ind in scanner_confirm_indicators.items()}
                            ctx2 = StrategyContext(
                                mode="live",
                                symbol=sym,
                                timeframe=tf,
                                indicators=ind2,
                                fees=fees,
                                positions={},
                                balances={},
                            )
                            intents2 = strategy.on_candle(c2[-1], ctx2)
                            if not intents2 or intents2[0].position_side != it.position_side:
                                ok = False
                                break
                        if not ok:
                            continue

                        price = float(entry_candles[-1].close)
                        ema_fast = (
                            float(entry_ind_results.get("ema_fast").values.get("ema"))
                            if entry_ind_results.get("ema_fast") and entry_ind_results.get("ema_fast").is_ready
                            else 0.0
                        )
                        ema_slow = (
                            float(entry_ind_results.get("ema_slow").values.get("ema"))
                            if entry_ind_results.get("ema_slow") and entry_ind_results.get("ema_slow").is_ready
                            else 0.0
                        )
                        rsi_v = (
                            float(entry_ind_results.get("rsi").values.get("rsi"))
                            if entry_ind_results.get("rsi") and entry_ind_results.get("rsi").is_ready
                            else 50.0
                        )
                        atr_v = (
                            float(entry_ind_results.get("atr").values.get("atr"))
                            if entry_ind_results.get("atr") and entry_ind_results.get("atr").is_ready
                            else 0.0
                        )
                        # Scoring: prefer trend strength but penalize "buying the top" and high-volatility assets
                        # (important when TP/SL are small).
                        trend = abs(ema_fast - ema_slow) / price if price else 0.0
                        atr_pct = (atr_v / price) if price else 0.0
                        # extension vs EMA fast, normalized by ATR (side-aware)
                        if it.position_side.value == "LONG":
                            extension = ((price - ema_fast) / atr_v) if atr_v else 0.0
                            rsi_pen = max(0.0, (rsi_v - 60.0) / 40.0)  # penalize very high RSI
                        else:
                            extension = ((ema_fast - price) / atr_v) if atr_v else 0.0
                            rsi_pen = max(0.0, (40.0 - rsi_v) / 40.0)  # penalize very low RSI for shorts
                        score = (trend * 1.0) - (max(0.0, extension) * 0.6) - (atr_pct * 0.8) - (rsi_pen * 0.4)
                        if best is None or score > best[0]:
                            best = (score, sym, it)
                    if best is None:
                        return None
                    return (best[1], best[2])

                last_traded_symbol: str | None = None
                completed = 0
                while completed < rounds:
                    if loss_streak_cooldown_until is not None:
                        now = datetime.now(timezone.utc)
                        if now >= loss_streak_cooldown_until:
                            risk.loss_streak.streak = 0
                            loss_streak_cooldown_until = None
                            log.info("Scanner loss_streak cooldown ended: streak reset, resuming scanning.")
                        else:
                            # Sleep a bit and keep waiting
                            await asyncio.sleep(min(5.0, (loss_streak_cooldown_until - now).total_seconds()))
                            continue
                    picked = await _pick_symbol(last_traded_symbol)
                    if picked is None:
                        log.warning("Scanner: no symbol matched the entry rules right now.")
                        if retry_on_no_match:
                            log.info("Scanner: retrying in %ss (completed=%s/%s)", retry_sleep_sec, completed, rounds)
                            await asyncio.sleep(retry_sleep_sec)
                            continue
                        return

                    picked_sym, picked_intent = picked
                    log.info("Scanner round %s/%s selected: %s side=%s", completed + 1, rounds, picked_sym, picked_intent.position_side.value)

                    # One-symbol registry for execution/routing
                    sym_registry = UniverseRegistry(symbols=[picked_sym], symbol_meta={picked_sym: universe_meta[picked_sym]})
                    router = OrderRouter(sym_registry.symbol_meta)
                    om = OrderManager(exchange=exchange, router=router, state=state, storage=None)

                    # Set leverage ONLY for the chosen symbol
                    lev = cfg.exchange.leverage_default or 1
                    eff_lev = int(lev)  # default to requested
                    try:
                        max_lev = None
                        try:
                            max_lev = await exchange.fetch_max_leverage(picked_sym)
                        except Exception as e:
                            log.debug("Failed fetching max leverage for %s: %s", picked_sym, e)
                        eff_lev = int(min(int(lev), int(max_lev))) if max_lev else int(lev)
                        if max_lev and eff_lev != int(lev):
                            log.warning("Leverage capped by exchange for %s: requested=%sx max=%sx using=%sx", picked_sym, lev, max_lev, eff_lev)
                        new_lev = await exchange.set_leverage(picked_sym, eff_lev)
                        log.info("Leverage set: %s -> %sx", picked_sym, new_lev)
                    except Exception as e:
                        log.warning("Failed setting leverage for %s: %s", picked_sym, e)

                    # Place immediately based on latest entry-timeframe close (no waiting)
                    klines = await exchange.fetch_klines(picked_sym, entry_timeframe, limit=int(entry_lookback))
                    hist_candles = klines_to_candles(picked_sym, entry_timeframe, klines)
                    history[picked_sym] = hist_candles[-cfg.market_data.candle_history :]
                    last_close = float(history[picked_sym][-1].close)
                    state.set_positions(await exchange.fetch_positions())

                    entry_ind_results = {name: ind.compute(hist_candles) for name, ind in scanner_entry_indicators.items()}
                    picked_intent = _apply_sizing(picked_intent, last_price=last_close, ind_results=entry_ind_results)
                    picked_intent = _apply_atr_exits(picked_intent, entry_ind_results, price=last_close)
                    picked_intent = _ensure_exit_meta(picked_intent)

                    # Adjust notional if leverage was capped (keep same margin, lower notional)
                    if eff_lev < int(lev) and picked_intent.notional_usdt:
                        orig_notional = picked_intent.notional_usdt
                        adjusted_notional = orig_notional * (eff_lev / int(lev))
                        log.info("Adjusting notional for capped leverage: %.4f -> %.4f (lev %sx -> %sx)",
                                 orig_notional, adjusted_notional, lev, eff_lev)
                        picked_intent = Intent(
                            symbol=picked_intent.symbol,
                            position_side=picked_intent.position_side,
                            action=picked_intent.action,
                            notional_usdt=adjusted_notional,
                            signal=picked_intent.signal,
                            prefer_maker=picked_intent.prefer_maker,
                            max_slippage_bps=picked_intent.max_slippage_bps,
                            meta=picked_intent.meta,
                        )

                    # Risk scope: if you have manual positions, you might still want the bot to trade small.
                    # "bot" scope means portfolio limits apply only to positions this run opens (not to manual positions).
                    if risk_scope == "bot":
                        bot_state = AccountState()
                        bot_state.set_balances(list(state.balances.values()))
                        bot_state.realized_pnl_usdt = state.realized_pnl_usdt
                        bot_state.fees_paid_usdt = state.fees_paid_usdt
                        bot_positions = [p for p in state.positions.values() if p.symbol in bot_active_symbols]
                        bot_state.set_positions(bot_positions)
                        dec = risk.validate_intent(picked_intent, state=bot_state, fees=fees, last_price=last_close)
                    else:
                        dec = risk.validate_intent(picked_intent, state=state, fees=fees, last_price=last_close)
                    decision_store.record(
                        DecisionRecord(
                            time=datetime.now(timezone.utc),
                            symbol=picked_sym,
                            action=picked_intent.action,
                            side=picked_intent.signal.value,
                            allowed=dec.allowed,
                            blocked_by=dec.blocked_by,
                            reason=dec.reason,
                            meta={
                                **dict(picked_intent.meta or {}),
                                "entry_indicators_used": sorted(list(scanner_entry_indicators.keys())),
                                "entry_indicators_snapshot": {
                                    k: {"is_ready": bool(v.is_ready), "values": dict(v.values)}
                                    for k, v in entry_ind_results.items()
                                },
                            },
                        )
                    )
                    if not dec.allowed:
                        ig = bool((picked_intent.meta or {}).get("ignore_fees_gate", False))
                        tp_pct_dbg = float((picked_intent.meta or {}).get("tp_pct", 0.0) or 0.0)
                        tp_usdt_dbg = float((picked_intent.meta or {}).get("tp_usdt", 0.0) or 0.0)
                        sl_usdt_dbg = float((picked_intent.meta or {}).get("sl_usdt", 0.0) or 0.0)
                        log.warning(
                            "Scanner intent blocked: %s %s (ignore_fees_gate=%s tp_pct=%.4f tp_usdt=%.4f sl_usdt=%.4f)",
                            dec.blocked_by,
                            dec.reason,
                            ig,
                            tp_pct_dbg,
                            tp_usdt_dbg,
                            sl_usdt_dbg,
                        )
                        if dec.blocked_by == "loss_streak" and loss_streak_cooldown_sec > 0:
                            loss_streak_cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=loss_streak_cooldown_sec)
                            log.warning(
                                "Scanner cooldown: loss_streak triggered. Pausing for %ss.",
                                loss_streak_cooldown_sec,
                            )
                            continue
                        if dec.blocked_by == "portfolio_limits":
                            positions = list(state.positions.values())
                            total = total_notional_usdt(positions)
                            pos_summary = ", ".join(
                                [
                                    f"{p.symbol}:{p.position_side.value} qty={p.quantity} mark={p.mark_price or 0:.8f}"
                                    for p in positions
                                ]
                            )
                            log.warning(
                                "Portfolio snapshot: positions=%s total_notional_usdt=%.2f limit=%.2f",
                                pos_summary or "(none)",
                                total,
                                cfg.risk.max_total_notional_usdt,
                            )
                            log.warning(
                                "To proceed: close any open positions (or increase risk.max_total_notional_usdt / max_total_positions)."
                            )
                            return
                        # don't update last_traded_symbol; just retry selection later
                        if retry_on_no_match:
                            await asyncio.sleep(retry_sleep_sec)
                            continue
                        return

                    try:
                        order = await om.submit_intent(picked_intent, last_price=last_close)
                    except Exception as e:
                        log.warning("Scanner order placement failed for %s: %s", picked_sym, e)
                        # Common case: -2019 Margin is insufficient -> stop the run early (no funds)
                        if "code=-2019" in str(e):
                            log.warning("Scanner stopping: margin insufficient. Top up futures wallet or lower notional.")
                            return
                        # Otherwise retry by scanning again later
                        if retry_on_no_match:
                            await asyncio.sleep(retry_sleep_sec)
                            continue
                        return
                    log.info(
                        "Scanner LIVE order placed: %s %s qty=%s price=%s",
                        picked_sym,
                        picked_intent.position_side.value,
                        order.executed_qty,
                        order.price,
                    )
                    log.info("Scanner: proceeding to bracket placement for %s...", picked_sym)
                    print(f"[PRINT] open_trade_id_by_symbol={list(open_trade_id_by_symbol.keys())} picked_sym={picked_sym}", flush=True)
                    # Trade open (for stats): one active trade per symbol (simple model)
                    # NOTE: trade_store.open_trade uses a blocking SQLite lock — run in executor to not block event loop
                    if picked_sym not in open_trade_id_by_symbol:
                        print(f"[PRINT] entering trade_store.open_trade for {picked_sym}", flush=True)
                        tid = uuid.uuid4().hex[:12]
                        rh = rules_hash((picked_intent.meta or {}).get("rules") or (picked_intent.meta or {}).get("entry_indicators_used") or {})
                        try:
                            print(f"[PRINT] calling trade_store.open_trade...", flush=True)
                            # Sync call — should be fast (SQLite local)
                            trade_store.open_trade(
                                trade_id=tid,
                                mode="live",
                                symbol=picked_sym,
                                timeframe=entry_timeframe,
                                direction=picked_intent.position_side.value,
                                rules_hash=rh,
                                entry_time=datetime.now(timezone.utc),
                                rules=(picked_intent.meta or {}).get("rules") or (picked_intent.meta or {}).get("entry_indicators_used"),
                                indicators_snapshot=(picked_intent.meta or {}).get("indicators_snapshot") or (picked_intent.meta or {}).get("entry_indicators_snapshot"),
                                meta={"source": "scanner", "entry_candle": (picked_intent.meta or {}).get("entry_candle")},
                            )
                            print(f"[PRINT] trade_store.open_trade completed", flush=True)
                        except Exception as e:
                            print(f"[PRINT] trade_store.open_trade FAILED: {e}", flush=True)
                            log.error("Scanner: failed to open trade record for %s: %s", picked_sym, e)
                        open_trade_id_by_symbol[picked_sym] = tid
                        open_trade_pnl_by_symbol[picked_sym] = 0.0
                        print(f"[PRINT] trade record created tid={tid}", flush=True)
                    print(f"[PRINT] adding to bot_active_symbols", flush=True)
                    bot_active_symbols.add(picked_sym)
                    print(f"[PRINT] preparing bracket_meta for {picked_sym}", flush=True)
                    bracket_meta_by_symbol[picked_sym] = {
                        **dict(picked_intent.meta or {}),
                        "entry_price": last_close,
                        "entry_time": datetime.now(timezone.utc).isoformat(),
                        "entry_rules": dict(picked_intent.meta or {}).get("rules"),
                        "entry_indicators_snapshot": dict(picked_intent.meta or {}).get("indicators_snapshot"),
                        "position_side": picked_intent.position_side.value,
                        "trail_high": last_close,
                        "trail_low": last_close,
                        "break_even_done": False,
                    }
                    print(f"[PRINT] bracket_meta prepared for {picked_sym}", flush=True)
                    try:
                        bracket_meta_for_log = {k: (picked_intent.meta or {}).get(k) for k in ["tp_pct","sl_pct","tp_usdt","sl_usdt","tp_levels","ignore_fees_gate"]}
                        print(f"[PRINT] calling _place_brackets_after_open for {picked_sym} meta={bracket_meta_for_log}", flush=True)
                        await _place_brackets_after_open(
                            picked_sym,
                            picked_intent,
                            qty_hint=float(order.executed_qty or 0.0),
                            entry_price_hint=float(order.price or last_close or 0.0),
                        )
                        print(f"[PRINT] _place_brackets_after_open COMPLETED for {picked_sym}", flush=True)
                    except Exception as e:
                        print(f"[PRINT] _place_brackets_after_open CRASHED for {picked_sym}: {e}", flush=True)
                        import traceback
                        traceback.print_exc()
                    state.set_positions(await exchange.fetch_positions())
                    state.set_balances(await exchange.fetch_balances())

                    if exit_after_entry:
                        log.info("Scanner exit_after_entry=true: exiting after placing entry+TP/SL.")
                        return

                    if exit_on_close:
                        log.info("Scanner exit_on_close=true: waiting until position is closed, then cleanup+continue.")
                        while True:
                            await asyncio.sleep(5.0)
                            state.set_positions(await exchange.fetch_positions())
                            pos_now = next((p for p in state.positions.values() if p.symbol == picked_sym), None)
                            if pos_now is not None:
                                meta = bracket_meta_by_symbol.get(picked_sym) or {}
                                entry_time_iso = str(meta.get("entry_time")) if meta.get("entry_time") else None
                                # Heal missing brackets while we wait (scanner doesn't stream candles, so no periodic ensure elsewhere).
                                await bracket_manager.ensure_for_position(
                                    symbol=picked_sym,
                                    position_side=pos_now.position_side,
                                    qty=float(pos_now.quantity),
                                    entry_price=float(pos_now.entry_price),
                                    tp_pct=float(meta.get("tp_pct", 0.0) or 0.0),
                                    sl_pct=float(meta.get("sl_pct", 0.0) or 0.0),
                                    tp_usdt=float(meta.get("tp_usdt", 0.0) or 0.0),
                                    sl_usdt=float(meta.get("sl_usdt", 0.0) or 0.0),
                                )
                                await _manage_open_position(
                                    sym=picked_sym,
                                    pos=pos_now,
                                    meta=meta,
                                    entry_time_iso=entry_time_iso,
                                    entry_timeframe=entry_timeframe,
                                    om=om,
                                )
                                continue
                            try:
                                await _cleanup_symbol(picked_sym)
                                log.info("Cleanup: ensured open orders cleared for %s", picked_sym)
                            except Exception as e:
                                log.warning("Cleanup failed for %s: %s", picked_sym, e)
                            try:
                                entry_ts = bracket_meta_by_symbol.get(picked_sym, {}).get("entry_time")
                                if entry_ts:
                                    entry_time = datetime.fromisoformat(entry_ts)
                                    pnl = float(open_trade_pnl_by_symbol.get(picked_sym, 0.0))
                                    decision_store.record(
                                        DecisionRecord(
                                            time=datetime.now(timezone.utc),
                                            symbol=picked_sym,
                                            action="CLOSE",
                                            side="AUTO",
                                            allowed=True,
                                            blocked_by=None,
                                            reason=None,
                                            meta={
                                                "realized_pnl_usdt": pnl,
                                                "entry_time": entry_ts,
                                                "exit_time": datetime.now(timezone.utc).isoformat(),
                                                "entry_rules": bracket_meta_by_symbol.get(picked_sym, {}).get("entry_rules"),
                                                "entry_indicators_snapshot": bracket_meta_by_symbol.get(picked_sym, {}).get(
                                                    "entry_indicators_snapshot"
                                                ),
                                            },
                                        )
                                    )
                                    tid = open_trade_id_by_symbol.pop(picked_sym, None)
                                    if tid:
                                        trade_store.close_trade(
                                            trade_id=tid,
                                            exit_time=datetime.now(timezone.utc),
                                            realized_pnl_usdt=pnl,
                                        )
                                    open_trade_pnl_by_symbol.pop(picked_sym, None)
                            except Exception as e:
                                log.debug("Trade summary record failed: %s", e)
                            break
                        bot_active_symbols.discard(picked_sym)
                        bracket_meta_by_symbol.pop(picked_sym, None)

                    completed += 1
                    last_traded_symbol = picked_sym
                    traded_symbols.add(picked_sym)
                    log.info("Scanner round %s/%s finished for %s.", completed, rounds, picked_sym)
                    if completed < rounds and sleep_between_rounds > 0:
                        await asyncio.sleep(sleep_between_rounds)

                log.info("Scanner finished: completed %s/%s rounds. Exiting.", completed, rounds)
                return

            # Set leverage for non-scanner (or after scanner has narrowed symbols)
            lev = cfg.exchange.leverage_default or 1
            for sym in symbols:
                try:
                    max_lev = None
                    try:
                        max_lev = await exchange.fetch_max_leverage(sym)
                    except Exception as e:
                        log.debug("Failed fetching max leverage for %s: %s", sym, e)
                    eff_lev = int(min(int(lev), int(max_lev))) if max_lev else int(lev)
                    if max_lev and eff_lev != int(lev):
                        log.warning("Leverage capped by exchange for %s: requested=%sx max=%sx using=%sx", sym, lev, max_lev, eff_lev)
                    new_lev = await exchange.set_leverage(sym, eff_lev)
                    log.info("Leverage set: %s -> %sx", sym, new_lev)
                except Exception as e:
                    log.warning("Failed setting leverage for %s: %s", sym, e)

            # Live kline stream (fan-in for small symbol counts)
            source = BinanceFuturesKlineWsSource(cfg.exchange.ws_base_url)
            for sym in symbols:
                log.info("Subscribing kline stream: %s %s", sym, cfg.market_data.timeframe)

            # DEMO: place immediately on startup (no waiting for indicator/warmup)
            if isinstance(strategy, DemoImmediateLongStrategy):
                sym0 = symbols[0]
                tickers = await exchange.fetch_24h_tickers()
                t = next((x for x in tickers if x.get("symbol") == sym0), None)
                last_price = float(t.get("lastPrice")) if t and t.get("lastPrice") else None
                if last_price is None:
                    raise RuntimeError("Could not fetch lastPrice for demo immediate order.")
                state.set_positions(await exchange.fetch_positions())
                if any(p.symbol == sym0 for p in state.positions.values()):
                    log.warning("Demo immediate skipped: position already open for %s", sym0)
                else:
                    intent = strategy.make_open_intent(sym0)
                    dec = risk.validate_intent(intent, state=state, fees=fees, last_price=last_price)
                    if not dec.allowed:
                        log.warning("Demo immediate blocked: %s %s", dec.blocked_by, dec.reason)
                    else:
                        order = await om.submit_intent(intent, last_price=last_price)
                        log.info(
                            "DEMO LIVE order placed: %s BUY LONG qty=%s price=%s orderId=%s",
                            sym0,
                            order.executed_qty,
                            order.price,
                            order.order_id,
                        )
                        demo_opened.add(sym0)
                        bracket_meta_by_symbol[sym0] = {
                            **dict(intent.meta or {}),
                            "entry_price": last_price,
                            "position_side": intent.position_side.value,
                            "trail_high": last_price,
                            "trail_low": last_price,
                            "break_even_done": False,
                        }
                        await _place_brackets_after_open(sym0, intent)
                        # resync after order
                        state.set_positions(await exchange.fetch_positions())
                        state.set_balances(await exchange.fetch_balances())

            async for candle in source.stream_many(symbols, cfg.market_data.timeframe):
                sym = candle.symbol
                history[sym].append(candle)
                history[sym] = history[sym][-cfg.market_data.candle_history :]

                # refresh state periodically (simple reconciliation)
                if len(history[sym]) % 10 == 0:
                    state.set_positions(await exchange.fetch_positions())
                    state.set_balances(await exchange.fetch_balances())
                    pos = next((p for p in state.positions.values() if p.symbol == sym), None)
                    meta = bracket_meta_by_symbol.get(sym)
                    if pos is not None and meta:
                        await bracket_manager.ensure_for_position(
                            symbol=sym,
                            position_side=pos.position_side,
                            qty=float(pos.quantity),
                            entry_price=float(pos.entry_price),
                            tp_pct=float(meta.get("tp_pct", 0.0)),
                            sl_pct=float(meta.get("sl_pct", 0.0)),
                            tp_usdt=float(meta.get("tp_usdt", 0.0)),
                            sl_usdt=float(meta.get("sl_usdt", 0.0)),
                        )

                # Advanced exits: break-even + trailing stop
                pos = next((p for p in state.positions.values() if p.symbol == sym), None)
                meta = bracket_meta_by_symbol.get(sym)
                if pos is not None and meta:
                    entry_price = float(meta.get("entry_price") or pos.entry_price)
                    trailing_pct = float(meta.get("trailing_stop_pct", 0.0))
                    break_even_pct = float(meta.get("break_even_pct", 0.0))
                    break_even_done = bool(meta.get("break_even_done", False))
                    px = float(candle.close)

                    # Break-even: move SL to entry when price moves in favor
                    if break_even_pct > 0 and not break_even_done:
                        if pos.position_side == PositionSide.LONG and px >= entry_price * (1.0 + break_even_pct / 100.0):
                            await bracket_manager.replace_sl_at_price(
                                symbol=sym,
                                position_side=pos.position_side,
                                qty=float(pos.quantity),
                                stop_price=entry_price,
                            )
                            meta["break_even_done"] = True
                        elif pos.position_side == PositionSide.SHORT and px <= entry_price * (1.0 - break_even_pct / 100.0):
                            await bracket_manager.replace_sl_at_price(
                                symbol=sym,
                                position_side=pos.position_side,
                                qty=float(pos.quantity),
                                stop_price=entry_price,
                            )
                            meta["break_even_done"] = True

                    # Trailing stop: update SL as price moves in favor
                    if trailing_pct > 0:
                        if pos.position_side == PositionSide.LONG:
                            meta["trail_high"] = max(float(meta.get("trail_high", px)), px)
                            trail_price = float(meta["trail_high"]) * (1.0 - trailing_pct / 100.0)
                        else:
                            meta["trail_low"] = min(float(meta.get("trail_low", px)), px)
                            trail_price = float(meta["trail_low"]) * (1.0 + trailing_pct / 100.0)
                        last_trail = float(meta.get("last_trail_price", 0.0))
                        if abs(trail_price - last_trail) > 0:
                            await bracket_manager.replace_sl_at_price(
                                symbol=sym,
                                position_side=pos.position_side,
                                qty=float(pos.quantity),
                                stop_price=trail_price,
                            )
                            meta["last_trail_price"] = trail_price

                ind_results = {name: ind.compute(history[sym]) for name, ind in indicators.items()}
                rsi_val = None
                if "rsi" in ind_results and ind_results["rsi"].is_ready:
                    rsi_val = ind_results["rsi"].values.get("rsi")
                log.info("Candle closed: %s close=%s rsi=%s", sym, candle.close, rsi_val)

                ctx = StrategyContext(
                    mode="live",
                    symbol=sym,
                    timeframe=candle.timeframe,
                    indicators=ind_results,
                    fees=fees,
                    positions={},
                    balances={},
                )

                has_position = any(p.symbol == sym for p in state.positions.values())
                if has_position:
                    had_position.add(sym)
                    open_candles[sym] = open_candles.get(sym, 0) + 1
                else:
                    open_candles.pop(sym, None)
                    if sym in had_position:
                        had_position.discard(sym)
                        try:
                            await bracket_manager.cleanup(sym)
                            log.info("Cleanup: ensured open orders cleared for %s", sym)
                        except Exception as e:
                            log.warning("Cleanup failed for %s: %s", sym, e)
                        bracket_meta_by_symbol.pop(sym, None)
                    if demo_mode and sym in demo_opened:
                        log.info("DEMO finished: position is closed for %s. Exiting.", sym)
                        return

                intents = strategy.on_candle(candle, ctx)
                if intents:
                    log.info("Strategy produced %s intent(s) for %s", len(intents), sym)
                for intent in intents:
                    # enforce simple state gating
                    if has_position and intent.action == "OPEN":
                        continue
                    if (not has_position) and intent.action != "OPEN":
                        continue

                    intent = _apply_sizing(intent, last_price=candle.close, ind_results=ind_results)
                    dec = risk.validate_intent(intent, state=state, fees=fees, last_price=candle.close)
                    decision_store.record(
                        DecisionRecord(
                            time=datetime.now(timezone.utc),
                            symbol=sym,
                            action=intent.action,
                            side=intent.signal.value,
                            allowed=dec.allowed,
                            blocked_by=dec.blocked_by,
                            reason=dec.reason,
                            meta=dict(intent.meta or {}),
                        )
                    )
                    if not dec.allowed:
                        log.warning("Intent blocked: %s %s", dec.blocked_by, dec.reason)
                        continue
                    order = await om.submit_intent(intent, last_price=candle.close)
                    log.info("LIVE order: %s %s %s qty=%s price=%s", sym, intent.signal.value, intent.position_side.value, order.executed_qty, order.price)

                    if intent.action == "OPEN":
                        bracket_meta_by_symbol[sym] = {
                            **dict(intent.meta or {}),
                            "entry_price": float(candle.close),
                            "position_side": intent.position_side.value,
                            "trail_high": float(candle.close),
                            "trail_low": float(candle.close),
                            "break_even_done": False,
                        }
                        await _place_brackets_after_open(sym, intent)
                        if demo_mode:
                            demo_opened.add(sym)

                    # resync after order
                    state.set_positions(await exchange.fetch_positions())
                    state.set_balances(await exchange.fetch_balances())

                # Time-stop close (demo-friendly): close position after N candles
                if has_position:
                    # Determine time stop from config (if present)
                    tstop = int(((cfg.strategy.exits or {}).get("time_stop") or {}).get("max_candles_in_trade", 0))
                    if tstop > 0 and open_candles.get(sym, 0) >= tstop:
                        # Close using reduceOnly market for approximate notional
                        pos = next((p for p in state.positions.values() if p.symbol == sym), None)
                        if pos is not None and pos.mark_price is not None:
                            notional = float(pos.quantity) * float(pos.mark_price)
                        elif pos is not None:
                            notional = float(pos.quantity) * float(candle.close)
                        else:
                            notional = float(cfg.strategy.sizing.get("notional_usdt", 10))
                        close_intent = Intent(
                            symbol=sym,
                            position_side=pos.position_side if pos else intent.position_side,
                            action="CLOSE",
                            notional_usdt=notional,
                            signal=Signal.SELL,
                            meta={"time_stop": True, "quantity": float(pos.quantity) if pos else 0.0},
                        )
                        dec = risk.validate_intent(close_intent, state=state, fees=fees, last_price=candle.close)
                        if dec.allowed:
                            close_order = await om.submit_intent(close_intent, last_price=candle.close)
                            log.info("Time-stop CLOSE: orderId=%s qty=%s price=%s", close_order.order_id, close_order.executed_qty, close_order.price)
                            open_candles.pop(sym, None)
                            state.set_positions(await exchange.fetch_positions())
                            state.set_balances(await exchange.fetch_balances())
                            if demo_mode:
                                # Cleanup any leftover conditional TP/SL algo orders to avoid surprises later.
                                try:
                                    await bracket_manager.cleanup(sym)
                                    log.info("DEMO cleanup: canceled open orders for %s", sym)
                                except Exception as e:
                                    log.warning("DEMO cleanup failed for %s: %s", sym, e)
                                log.info("DEMO finished: time-stop close submitted for %s. Exiting.", sym)
                                return
        finally:
            if keepalive_task:
                keepalive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keepalive_task
            if user_stream:
                await user_stream.stop()
            await exchange.close()

