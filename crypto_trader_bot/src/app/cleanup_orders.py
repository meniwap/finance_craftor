from __future__ import annotations

import argparse
import asyncio

from src.core.config import load_config
from src.core.env import load_dotenv
from src.exchange.adapters.auth import load_keys_from_env
from src.exchange.adapters.rate_limiter import SimpleRateLimiter
from src.exchange.binance.futures_client import BinanceFuturesUsdtmClient


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cleanup_orders")
    p.add_argument("--config", required=True, help="YAML config with exchange settings")
    p.add_argument("--symbol", required=True, help="Symbol to cleanup (e.g., BTCUSDT)")
    return p


async def _amain(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    load_dotenv(".env")
    cfg = load_config(args.config)
    keys = load_keys_from_env()
    ex = BinanceFuturesUsdtmClient(cfg=cfg.exchange, keys=keys, limiter=SimpleRateLimiter(max_per_sec=5))
    try:
        await ex.cancel_all_open_algo_orders(args.symbol)
        await ex.cancel_all_open_orders(args.symbol)
        print(f"Cleanup requested for {args.symbol}: canceled algoOpenOrders + allOpenOrders")
    finally:
        await ex.close()
    return 0


def main() -> None:
    import sys

    raise SystemExit(asyncio.run(_amain(sys.argv[1:])))


if __name__ == "__main__":
    main()

