from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Allow running this script directly (ensure project root is on sys.path).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import load_config
from src.core.types import Intent, PositionSide, Signal
from src.execution.bracket_manager import BracketManager
from src.execution.order_manager import OrderManager
from src.execution.router import OrderRouter
from src.exchange.adapters.auth import load_keys_from_env
from src.exchange.adapters.rate_limiter import SimpleRateLimiter
from src.exchange.adapters.symbol_mapper import parse_exchange_info
from src.exchange.binance.futures_client import BinanceFuturesUsdtmClient
from src.portfolio.account_state import AccountState


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _fetch_last_price(exchange: BinanceFuturesUsdtmClient, symbol: str) -> float:
    klines = await exchange.fetch_klines(symbol, "1m", limit=1)
    if not klines:
        raise RuntimeError(f"No klines returned for {symbol}")
    # kline: [open_time, open, high, low, close, ...]
    close_price = float(klines[-1][4])
    return close_price


async def _wait_for_position(
    exchange: BinanceFuturesUsdtmClient,
    symbol: str,
    *,
    retries: int = 10,
    sleep_sec: float = 0.5,
) -> tuple[float, float] | None:
    for _ in range(retries):
        positions = await exchange.fetch_positions()
        pos = next((p for p in positions if p.symbol == symbol), None)
        if pos and pos.quantity > 0:
            return (float(pos.quantity), float(pos.entry_price))
        await asyncio.sleep(sleep_sec)
    return None


async def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config_path)
    keys = load_keys_from_env()

    exchange = BinanceFuturesUsdtmClient(cfg=cfg.exchange, keys=keys, limiter=SimpleRateLimiter(max_per_sec=5))
    try:
        exch_info = await exchange.fetch_exchange_info()
        symbol_meta = parse_exchange_info(exch_info)
        if args.symbol not in symbol_meta:
            raise RuntimeError(f"Symbol {args.symbol} not found in exchangeInfo")

        # Set leverage
        lev = int(args.leverage)
        try:
            max_lev = await exchange.fetch_max_leverage(args.symbol)
            if max_lev and lev > max_lev:
                logging.warning("Leverage capped by exchange: requested=%s max=%s", lev, max_lev)
                lev = int(max_lev)
        except Exception as e:
            logging.warning("Failed fetching max leverage: %s", e)
        new_lev = await exchange.set_leverage(args.symbol, lev)
        logging.info("Leverage set: %s -> %sx", args.symbol, new_lev)

        # Compute notional and last price
        last_price = await _fetch_last_price(exchange, args.symbol)
        notional = float(args.margin_usdt) * float(new_lev)
        logging.info("Last price: %.8f | Margin: %.4f | Notional: %.4f", last_price, args.margin_usdt, notional)

        # Submit MARKET entry via OrderManager (handles step size/min notional)
        intent = Intent(
            symbol=args.symbol,
            position_side=PositionSide.LONG if args.side.upper() == "LONG" else PositionSide.SHORT,
            action="OPEN",
            notional_usdt=notional,
            signal=Signal.BUY if args.side.upper() == "LONG" else Signal.SELL,
            meta={"source": "cli_demo"},
        )
        router = OrderRouter(symbol_meta)
        state = AccountState()
        om = OrderManager(exchange=exchange, router=router, state=state, storage=None)

        order = await om.submit_intent(intent, last_price=last_price)
        logging.info("Entry order placed: id=%s qty=%.8f price=%.8f type=%s", order.order_id, order.executed_qty, float(order.price or 0.0), order.order_type.value)

        # Fetch actual position (if available)
        pos_info = await _wait_for_position(exchange, args.symbol)
        if pos_info:
            qty, entry_price = pos_info
            logging.info("Position confirmed: qty=%.8f entry=%.8f", qty, entry_price)
        else:
            qty = float(order.executed_qty or 0.0)
            entry_price = float(order.price or last_price)
            logging.warning("Position not visible; using order hints qty=%.8f entry=%.8f", qty, entry_price)

        # Place brackets (TP/SL)
        bracket_manager = BracketManager(
            exchange=exchange,
            symbol_meta=symbol_meta,
            tp_kind=str(args.tp_kind).lower(),
            sl_kind=str(args.sl_kind).lower(),
            limit_offset_ticks=int(args.limit_offset_ticks),
        )
        logging.info(
            "Placing brackets: tp_usdt=%.4f sl_usdt=%.4f tp_kind=%s sl_kind=%s",
            args.tp_usdt,
            args.sl_usdt,
            args.tp_kind,
            args.sl_kind,
        )
        orders = await bracket_manager.place_for_position(
            symbol=args.symbol,
            position_side=intent.position_side,
            qty=qty,
            entry_price=entry_price,
            tp_pct=0.0,
            sl_pct=0.0,
            tp_usdt=float(args.tp_usdt),
            sl_usdt=float(args.sl_usdt),
        )
        logging.info("Bracket orders placed: tp_id=%s sl_id=%s", orders.tp_order_id, orders.sl_order_id)

        # Fetch open orders to verify
        open_orders = await exchange.fetch_open_orders(args.symbol)
        logging.info("Open orders count=%s", len(open_orders))
        for o in open_orders:
            logging.info("OpenOrder: type=%s side=%s price=%s stopPrice=%s reduceOnly=%s",
                         o.get("type"), o.get("side"), o.get("price"), o.get("stopPrice"), o.get("reduceOnly"))
        try:
            algo_orders = await exchange.fetch_open_algo_orders(args.symbol)
            logging.info("Open algo orders count=%s", len(algo_orders))
            for o in algo_orders:
                logging.info("AlgoOrder: type=%s side=%s price=%s triggerPrice=%s reduceOnly=%s",
                             o.get("type"), o.get("side"), o.get("price"), o.get("triggerPrice"), o.get("reduceOnly"))
        except Exception as e:
            logging.debug("fetch_open_algo_orders failed: %s", e)

        return 0
    finally:
        await exchange.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Place a demo futures entry + TP/SL brackets (no UI).")
    p.add_argument("--symbol", default="FARTCOINUSDT")
    p.add_argument("--side", choices=["LONG", "SHORT"], default="LONG")
    p.add_argument("--margin-usdt", type=float, default=1.0)
    p.add_argument("--leverage", type=int, default=50)
    p.add_argument("--tp-usdt", type=float, default=0.2)
    p.add_argument("--sl-usdt", type=float, default=0.2)
    p.add_argument("--tp-kind", choices=["limit", "market"], default="limit")
    p.add_argument("--sl-kind", choices=["market", "limit"], default="market")
    p.add_argument("--limit-offset-ticks", type=int, default=0)
    p.add_argument("--config-path", default="configs/live_scanner_top40_5m_5rounds_1usd_20c.yaml")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    _setup_logging(args.verbose)
    logging.info("Starting bracket demo: %s", {k: v for k, v in vars(args).items() if k != "verbose"})
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logging.warning("Interrupted by user.")


if __name__ == "__main__":
    main()
