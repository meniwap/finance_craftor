#!/usr/bin/env bash
set -euo pipefail

python -m src.app.main backtest --config configs/default.yaml

