from __future__ import annotations

import argparse
import asyncio
import sys

from src.app.bootstrap import build_runtime
from src.core.config import load_config
from src.core.env import load_dotenv


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crypto_trader_bot")
    p.add_argument("mode", choices=["backtest", "paper", "live"])
    p.add_argument("--config", required=True, help="Path to YAML config (e.g., configs/default.yaml)")
    return p


async def _amain(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    load_dotenv(".env")
    cfg = load_config(args.config)
    runtime = build_runtime(cfg, mode=args.mode)
    await runtime.run()
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_amain(sys.argv[1:]))
    except KeyboardInterrupt:
        rc = 130
    raise SystemExit(rc)


if __name__ == "__main__":
    main()

