from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.app.bootstrap import build_runtime
from src.app.session_manager import SessionManager
from src.app.session_store import SessionStore
from src.indicators.registry import IndicatorRegistry
from src.strategies.registry import StrategyRegistry
from src.strategies.composer import compose_strategy_config
from src.monitoring.decision_store import DecisionStore
from src.monitoring.fill_store import FillStore
from src.monitoring.trade_store import TradeStore
from src.monitoring.stats import aggregate_stats, current_loss_streak
from src.core.config import _deep_merge, load_config
from src.core.types import Intent, PositionSide, Signal
from src.exchange.adapters.auth import load_keys_from_env
from src.exchange.adapters.rate_limiter import SimpleRateLimiter
from src.exchange.binance.futures_client import BinanceFuturesUsdtmClient
from src.execution.bracket_manager import BracketManager
from src.execution.order_manager import OrderManager
from src.execution.router import OrderRouter
from src.monitoring.logger import setup_logging, get_logger
from src.portfolio.account_state import AccountState
from src.universe.selector import UniverseSelector

app = FastAPI()
log = get_logger("ui")


def _binance_auth_hint_from_error(msg: str) -> str | None:
    """
    Binance futures client errors often look like:
      'Binance API error: http=401 code=-2015 msg=Invalid API-key, IP, or permissions for action, request ip: X.X.X.X'
    """
    if "code=-2015" not in msg:
        return None
    # Keep it simple: surface the IP if present so the user can whitelist it quickly.
    ip = None
    if "request ip:" in msg:
        ip = msg.split("request ip:", 1)[1].strip()
    if ip:
        return f"Binance auth failed (code=-2015). Whitelist this IP in Binance API settings: {ip}"
    return "Binance auth failed (code=-2015). Check API key, IP whitelist, and futures permissions."

def _ui_mode() -> str:
    # live: allow everything (subject to existing live gates)
    # paper_only: blocks cfg.mode == "live"
    # read_only: blocks all write operations
    return (os.getenv("UI_MODE") or "live").strip().lower()


def _ui_token_expected() -> str:
    return (os.getenv("UI_TOKEN") or "").strip()


def require_ui_token(
    x_ui_token: str | None = Header(default=None, alias="X-UI-TOKEN"),
    ui_token: str | None = Query(default=None),
) -> None:
    expected = _ui_token_expected()
    if not expected:
        return
    if x_ui_token == expected or ui_token == expected:
        return
    raise HTTPException(status_code=401, detail="missing/invalid UI token")


def require_write_allowed() -> None:
    if _ui_mode() == "read_only":
        raise HTTPException(status_code=403, detail="UI is in read-only mode")


def require_live_allowed(*, cfg_mode: str, confirm_live: bool) -> None:
    cfg_mode = (cfg_mode or "").strip().lower()
    if cfg_mode != "live":
        return
    if _ui_mode() == "paper_only":
        raise HTTPException(status_code=403, detail="UI is in paper-only mode (live blocked)")
    if os.getenv("UI_REQUIRE_LIVE_CONFIRM", "").strip().lower() in {"1", "true", "yes"} and not confirm_live:
        raise HTTPException(status_code=403, detail="live requires confirm_live=true")


@app.get("/ui_meta")
def ui_meta() -> dict[str, Any]:
    return {
        "ui_mode": _ui_mode(),
        "token_required": bool(_ui_token_expected()),
        "require_live_confirm": os.getenv("UI_REQUIRE_LIVE_CONFIRM", "").strip().lower() in {"1", "true", "yes"},
    }


@dataclass
class BotRunner:
    task: asyncio.Task[None] | None = None
    loop: asyncio.AbstractEventLoop | None = None
    thread: threading.Thread | None = None

    def start(self, config_path: str) -> None:
        if self.task and not self.task.done():
            raise RuntimeError("Bot already running")

        def _run() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            cfg = load_config(config_path)
            runtime = build_runtime(cfg=cfg, mode=cfg.mode)
            self.task = self.loop.create_task(runtime.run())
            try:
                self.loop.run_until_complete(self.task)
            except asyncio.CancelledError:
                # stop() cancels the task; this is expected
                pass

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.loop and self.task and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)


runner = BotRunner()
session_store = SessionStore("data/sessions.sqlite3")
session_store.init_schema()
sessions = SessionManager(store=session_store)
indicator_registry = IndicatorRegistry()
strategy_registry = StrategyRegistry()
decision_store = DecisionStore("data/decisions.sqlite3")
decision_store.init_schema()
fill_store = FillStore("data/fills.sqlite3")
fill_store.init_schema()
trade_store = TradeStore("data/trades.sqlite3")
trade_store.init_schema()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html_path = Path(__file__).resolve().parent.parent / "ui" / "index.html"
    return html_path.read_text()


@app.post("/start")
def start_bot(payload: dict[str, Any], _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    # Backward-compatible simple start (single runner)
    require_write_allowed()
    config_path = str(payload.get("config_path", "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml"))
    try:
        cfg = load_config(config_path)
        require_live_allowed(cfg_mode=cfg.mode, confirm_live=bool(payload.get("confirm_live", False)))
        runner.start(config_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "started", "config_path": config_path}


@app.post("/stop")
def stop_bot(_: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    runner.stop()
    return {"status": "stopping"}


@app.post("/sessions")
def create_session(payload: dict[str, Any], _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    base_path = str(payload.get("base_config_path", "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml"))
    overrides = payload.get("overrides") or {}
    try:
        sess = sessions.create_session(base_config_path=base_path, overrides=overrides)
    except Exception as e:
        log.exception("create_session failed")
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"session_id": sess.session_id, "status": sess.status}


@app.post("/sessions/from_ui")
def create_session_from_ui(payload: dict[str, Any], _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    base_path = str(payload.get("base_config_path", "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml"))
    overrides = payload.get("overrides") or {}
    if "strategy_composer" in payload:
        composed = compose_strategy_config(payload["strategy_composer"])

        # IMPORTANT: the UI may also send overrides.strategy (e.g. scanner.confirm_timeframes=[]).
        # Do NOT drop those. Merge them into the composed strategy config.
        strategy_override = overrides.get("strategy") if isinstance(overrides, dict) else None
        if isinstance(strategy_override, dict) and strategy_override:
            composed = _deep_merge(composed, strategy_override)

        # Also ensure tp_usdt/sl_usdt are passed from UI if specified
        # The UI may send these at the top level or inside strategy_composer
        tp_usdt_ui = payload.get("tp_usdt") or payload.get("strategy_composer", {}).get("tp_usdt")
        sl_usdt_ui = payload.get("sl_usdt") or payload.get("strategy_composer", {}).get("sl_usdt")
        tp_atr_mult_ui = payload.get("tp_atr_mult") or payload.get("strategy_composer", {}).get("tp_atr_mult")
        sl_atr_mult_ui = payload.get("sl_atr_mult") or payload.get("strategy_composer", {}).get("sl_atr_mult")
        ignore_fees_gate_ui = payload.get("ignore_fees_gate") or payload.get("strategy_composer", {}).get("ignore_fees_gate")

        # Inject TP/SL into the composed strategy's signals section
        composed_signals = dict(composed.get("signals") or {})
        strat_name = str(composed.get("name", "rule_combo"))
        strat_signals = dict(composed_signals.get(strat_name, {}))
        if tp_usdt_ui is not None:
            strat_signals["tp_usdt"] = float(tp_usdt_ui)
        if sl_usdt_ui is not None:
            strat_signals["sl_usdt"] = float(sl_usdt_ui)
        if tp_atr_mult_ui is not None:
            strat_signals["tp_atr_mult"] = float(tp_atr_mult_ui)
        if sl_atr_mult_ui is not None:
            strat_signals["sl_atr_mult"] = float(sl_atr_mult_ui)
        if ignore_fees_gate_ui is not None:
            strat_signals["ignore_fees_gate"] = bool(ignore_fees_gate_ui)
        if strat_signals:
            composed_signals[strat_name] = strat_signals
            composed["signals"] = composed_signals

        log.info(
            "UI session TP/SL injection: tp_usdt=%s sl_usdt=%s tp_atr_mult=%s sl_atr_mult=%s ignore_fees=%s",
            tp_usdt_ui, sl_usdt_ui, tp_atr_mult_ui, sl_atr_mult_ui, ignore_fees_gate_ui,
        )

        # Extract indicators from composed strategy and inject into scanner config
        # so Scanner uses the UI-selected indicators instead of YAML defaults.
        ui_indicators = composed.get("indicators") or {}
        if isinstance(ui_indicators, dict) and ui_indicators:
            existing_signals = dict(composed.get("signals") or {})
            existing_scanner = dict(existing_signals.get("scanner") or {})
            existing_scanner["entry_indicators"] = ui_indicators
            existing_scanner["confirm_indicators"] = ui_indicators
            existing_signals["scanner"] = existing_scanner
            composed["signals"] = existing_signals

        # Replace ONLY strategy in overrides (keep other override sections: exchange/risk/etc)
        if isinstance(overrides, dict):
            overrides = {**overrides, "strategy": composed}
        else:
            overrides = {"strategy": composed}

        log.info(
            "UI session composed strategy: indicators=%s",
            list(ui_indicators.keys()) if isinstance(ui_indicators, dict) else [],
        )
    try:
        sess = sessions.create_session(base_config_path=base_path, overrides=overrides)
    except Exception as e:
        log.exception("create_session_from_ui failed")
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"session_id": sess.session_id, "status": sess.status}


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    try:
        sess = sessions.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    last_error = None
    for e in reversed(sess.events):
        if e.type == "error":
            last_error = e.data.get("error")
            break
    return {
        "session_id": sess.session_id,
        "status": sess.status,
        "base_config_path": sess.base_config_path,
        "overrides": sess.overrides,
        "paused": sess.paused,
        "last_error": last_error,
    }


@app.post("/sessions/{session_id}/start")
def start_session(session_id: str, confirm_live: bool = False, _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    try:
        sess = sessions.get(session_id)
        require_live_allowed(cfg_mode=sess.config.mode, confirm_live=confirm_live)
        sessions.start(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        sess = sessions.get(session_id)
        status = sess.status
    except Exception:
        status = "starting"
    return {"session_id": session_id, "status": status}


@app.post("/sessions/{session_id}/stop")
def stop_session(session_id: str, _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    try:
        sessions.stop(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"session_id": session_id, "status": "stopping"}


@app.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    try:
        sessions.pause(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "paused": True}


@app.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    try:
        sessions.resume(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "paused": False}


@app.get("/sessions/{session_id}/events")
def session_events(session_id: str) -> dict[str, Any]:
    try:
        sess = sessions.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    events = [{"type": e.type, "data": e.data} for e in sess.events]
    try:
        events = session_store.list_events(session_id)
    except Exception:
        pass
    return {"session_id": session_id, "events": events}


@app.get("/registry/indicators")
def registry_indicators() -> dict[str, Any]:
    items = indicator_registry.list_available()
    return {"items": [i.__dict__ for i in items]}


@app.get("/registry/strategies")
def registry_strategies() -> dict[str, Any]:
    items = strategy_registry.list_available()
    return {"items": [i.__dict__ for i in items]}


@app.get("/registry/sizing")
def registry_sizing() -> dict[str, Any]:
    items = strategy_registry.list_sizing()
    return {"items": [i.__dict__ for i in items]}


@app.get("/decisions")
def decisions(limit: int = 200) -> dict[str, Any]:
    return {"items": decision_store.list_recent(limit=limit)}


@app.get("/fills")
def fills(limit: int = 200) -> dict[str, Any]:
    return {"items": fill_store.list_recent(limit=limit)}


@app.get("/trades")
def trades(mode: str | None = None, limit: int = 200) -> dict[str, Any]:
    return {"items": trade_store.list_recent(mode=mode, limit=limit)}


@app.get("/stats/details")
def stats_details(rules_hash: str, mode: str | None = None, limit: int = 50) -> dict[str, Any]:
    items = trade_store.list_by_rules_hash(rules_hash=rules_hash, mode=mode, limit=limit)
    return {"items": items}


@app.get("/stats")
def stats(mode: str | None = None, timeframe: str | None = None, direction: str | None = None) -> dict[str, Any]:
    rows = aggregate_stats(trade_store, mode=mode, timeframe=timeframe, direction=direction)
    return {"items": [r.__dict__ for r in rows]}


@app.get("/risk_status")
def risk_status(config_path: str = "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml", mode: str = "live") -> dict[str, Any]:
    cfg = load_config(config_path)
    recent = trade_store.list_closed(mode=mode, limit=50)
    streak = current_loss_streak(recent)
    return {
        "mode": mode,
        "loss_streak_current": streak,
        "loss_streak_limit": int(cfg.risk.loss_streak_limit),
    }


@app.get("/last_blocks")
def last_blocks(limit: int = 50) -> dict[str, Any]:
    """
    Convenience endpoint to help users understand why entries were blocked recently.
    """
    items = decision_store.list_recent(limit=limit)
    blocked = [x for x in items if not x.get("allowed", True)]
    return {"items": blocked}


@app.get("/block_summary")
def block_summary(limit: int = 200) -> dict[str, Any]:
    """
    Summarize recent block reasons for quick UI diagnostics.
    """
    items = decision_store.list_recent(limit=limit)
    counts: dict[str, int] = {}
    examples: dict[str, dict[str, Any]] = {}
    for x in items:
        if x.get("allowed", True):
            continue
        key = str(x.get("blocked_by") or x.get("reason") or "unknown")
        counts[key] = counts.get(key, 0) + 1
        if key not in examples:
            examples[key] = x
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return {"counts": top, "examples": examples}


@app.get("/sessions")
def list_sessions() -> dict[str, Any]:
    items = []
    for s in sessions.list():
        items.append(
            {
                "session_id": s.session_id,
                "status": s.status,
                "base_config_path": s.base_config_path,
                "paused": s.paused,
            }
        )
    return {"items": items}


@app.post("/sessions/{session_id}/clone")
def clone_session(session_id: str, _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    try:
        sess = sessions.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        new_sess = sessions.create_session(base_config_path=sess.base_config_path, overrides=sess.overrides)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"session_id": new_sess.session_id, "status": new_sess.status}


@app.get("/open_orders")
async def open_orders(config_path: str = "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml", symbol: str | None = None) -> dict[str, Any]:
    cfg = load_config(config_path)
    try:
        keys = load_keys_from_env()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    exchange = BinanceFuturesUsdtmClient(cfg=cfg.exchange, keys=keys, limiter=SimpleRateLimiter(max_per_sec=5))
    try:
        syms: list[str]
        if symbol:
            syms = [symbol.upper()]
        else:
            # best-effort: query per-symbol for current open positions to limit API calls
            try:
                syms = sorted({p.symbol for p in (await exchange.fetch_positions())})
            except Exception as e:
                hint = _binance_auth_hint_from_error(str(e))
                if hint:
                    raise HTTPException(status_code=401, detail=hint) from e
                raise HTTPException(status_code=400, detail=str(e)) from e
        reg: list[dict[str, Any]] = []
        algo: list[dict[str, Any]] = []
        for s in syms:
            try:
                reg.extend(await exchange.fetch_open_orders(s))
            except Exception:
                pass
            try:
                algo.extend(await exchange.fetch_open_algo_orders(s))
            except Exception:
                pass
        return {"regular": reg, "algo": algo, "symbols": syms}
    finally:
        await exchange.close()


@app.post("/compose")
def compose(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        cfg = compose_strategy_config(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"strategy": cfg}


@app.post("/sessions/{session_id}/run_rounds")
def run_rounds(session_id: str, payload: dict[str, Any], _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    require_write_allowed()
    try:
        sessions.record_command(session_id, name="run_rounds", params=payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "status": "queued"}


@app.post("/manual_intent")
async def manual_intent(payload: dict[str, Any], _: Any = Depends(require_ui_token)) -> dict[str, Any]:
    """
    Manual trade endpoint:
    - symbol, side (BUY/SELL), notional_usdt
    - optional: tp_usdt, sl_usdt, leverage
    """
    session_id = payload.get("session_id")
    if session_id:
        try:
            sess = sessions.get(str(session_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="session not found")
        cfg = sess.config
    else:
        config_path = str(payload.get("config_path", "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml"))
        cfg = load_config(config_path)
    require_write_allowed()
    require_live_allowed(cfg_mode=cfg.mode, confirm_live=bool(payload.get("confirm_live", False)))
    setup_logging(cfg.logging.level)

    symbol = str(payload.get("symbol", "")).upper()
    side = str(payload.get("side", "BUY")).upper()
    notional = float(payload.get("notional_usdt", 0))
    if not symbol or notional <= 0:
        raise HTTPException(status_code=400, detail="symbol and notional_usdt are required")

    try:
        keys = load_keys_from_env()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    exchange = BinanceFuturesUsdtmClient(cfg=cfg.exchange, keys=keys, limiter=SimpleRateLimiter(max_per_sec=5))
    try:
        selector = UniverseSelector(cfg.universe)
        registry = await selector.refresh(exchange)
        if symbol not in registry.symbols:
            registry.symbols.append(symbol)
        router = OrderRouter(registry.symbol_meta)
        state = AccountState()
        state.set_positions(await exchange.fetch_positions())
        state.set_balances(await exchange.fetch_balances())
        om = OrderManager(exchange=exchange, router=router, state=state, storage=None)

        leverage = payload.get("leverage")
        if leverage is not None:
            try:
                await exchange.set_leverage(symbol, int(leverage))
            except Exception as e:
                log.warning("Leverage set failed: %s", e)

        last_price = float(payload.get("last_price", 0.0))
        if last_price <= 0:
            tickers = await exchange.fetch_24h_tickers()
            t = next((x for x in tickers if x.get("symbol") == symbol), None)
            last_price = float(t.get("lastPrice")) if t and t.get("lastPrice") else 0.0
        if last_price <= 0:
            raise HTTPException(status_code=400, detail="last_price missing and ticker unavailable")

        intent = Intent(
            symbol=symbol,
            position_side=PositionSide.LONG if side == "BUY" else PositionSide.SHORT,
            action="OPEN",
            notional_usdt=float(notional),
            signal=Signal.BUY if side == "BUY" else Signal.SELL,
            meta={
                "tp_usdt": float(payload.get("tp_usdt", 0.0)),
                "sl_usdt": float(payload.get("sl_usdt", 0.0)),
            },
        )

        order = await om.submit_intent(intent, last_price=last_price)

        # Place brackets if requested
        if intent.meta.get("tp_usdt", 0.0) > 0 or intent.meta.get("sl_usdt", 0.0) > 0:
            bracket_manager = BracketManager(
                exchange=exchange,
                symbol_meta=registry.symbol_meta,
                tp_kind=str(payload.get("tp_order_kind", "limit")).lower(),
                sl_kind=str(payload.get("sl_order_kind", "market")).lower(),
                limit_offset_ticks=int(payload.get("limit_offset_ticks", 0)),
            )
            positions = await exchange.fetch_positions()
            pos = next((p for p in positions if p.symbol == symbol), None)
            if pos:
                await bracket_manager.place_for_position(
                    symbol=symbol,
                    position_side=pos.position_side,
                    qty=float(pos.quantity),
                    entry_price=float(pos.entry_price),
                    tp_pct=0.0,
                    sl_pct=0.0,
                    tp_usdt=float(intent.meta.get("tp_usdt", 0.0)),
                    sl_usdt=float(intent.meta.get("sl_usdt", 0.0)),
                )

        return {"status": "ok", "order_id": order.order_id}
    finally:
        await exchange.close()


@app.get("/state")
async def get_state(config_path: str = "configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml", session_id: str | None = None) -> dict[str, Any]:
    if session_id:
        try:
            cfg = sessions.get(session_id).config
        except KeyError:
            raise HTTPException(status_code=404, detail="session not found")
    else:
        cfg = load_config(config_path)
    try:
        keys = load_keys_from_env()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    exchange = BinanceFuturesUsdtmClient(cfg=cfg.exchange, keys=keys, limiter=SimpleRateLimiter(max_per_sec=5))
    try:
        try:
            balances = await exchange.fetch_balances()
            positions = await exchange.fetch_positions()
        except Exception as e:
            hint = _binance_auth_hint_from_error(str(e))
            if hint:
                raise HTTPException(status_code=401, detail=hint) from e
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {
            "balances": [b.__dict__ for b in balances],
            "positions": [p.__dict__ for p in positions],
        }
    finally:
        await exchange.close()
