# crypto_trader_bot

Modular Binance Futures (USDT-M) trading bot with multi-symbol engine, backtest/paper/live parity, and mandatory risk guards.

## Quickstart (after dependencies installed)

## Local UI (recommended)

Run the local FastAPI UI to create/start sessions without editing YAML:

```bash
. .venv/bin/activate
python -m uvicorn src.app.ui_server:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000/`

Optional (recommended) safety controls:

```bash
# Require a token for all write operations from the UI
export UI_TOKEN="change-me"

# Block live starts from UI (paper/backtest only)
export UI_MODE="paper_only"

# Require explicit confirmation checkbox before live actions
export UI_REQUIRE_LIVE_CONFIRM="true"
```

See `docs/runbook_ui.md`.

## Configuration

- Copy `env.example` to `.env` and fill Binance keys.
- Live is **disabled by default** via `LIVE_ENABLED=false`.

### Backtest

```bash
python -m src.app.main backtest --config configs/default.yaml
```

### Paper

```bash
python -m src.app.main paper --config configs/default.yaml
```

### Live (locked by default)

```bash
python -m src.app.main live --config configs/default.yaml
```

## Safety

This project is research software. Futures trading is high risk. Live mode should remain disabled until:

- reconciliation is verified
- risk guards are passing tests
- fees/funding breakeven gating is enabled

