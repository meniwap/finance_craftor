# Live Runbook (Safety First)

## Preconditions (do not skip)

- Backtest completed across multiple market regimes (trend up/down/range)
- Paper trading stable for 1–2 weeks, with logs and reconciliation checks
- Risk guards enabled and tested (loss limits, max exposure, leverage caps)
- Breakeven gate enabled (fees + slippage + funding estimate)
- Kill switch tested (manual and automatic trigger)

## Live defaults

- Isolated margin
- One-way mode
- Low leverage (<= 2–3)
- TOP-N small universe (e.g., 10–20)
- Small notional per trade

## Operational checklist

### Before starting

- Confirm `LIVE_ENABLED=true` in environment and `risk.live_enabled=true` in config
- Confirm API keys are **trade-enabled** and scoped correctly
- Confirm clock sync is within tolerance

### During run

- Monitor:
  - open positions count
  - total notional exposure
  - liquidation distance
  - PnL net of fees/funding
  - order rejections / latency

### Emergency

- Trigger kill switch:
  - cancel all open orders
  - stop placing new orders
  - (optional) close positions if configured

