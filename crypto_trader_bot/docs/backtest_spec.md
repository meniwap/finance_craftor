# Backtest spec (Parity with Paper)

## Goal

Backtest results should be directionally consistent with Paper mode by sharing:

- Strategy code
- Indicator computations
- Risk rules and guards
- Fee model and breakeven gating
- Slippage model (configurable)
- Order lifecycle model (fills, partials, cancels)

## Event model

Backtest engine should emit the same events as live:

- `CandleClosed`
- `OrderUpdate`
- `FillEvent`
- `FundingEvent` (synthetic)
- `RiskHalt`

## Fill simulation

### Simplified (MVP)

- Market orders fill on candle close price ± slippage.
- Limit orders fill if candle high/low crosses limit price (conservative rules configurable).
- Partial fills: optional in MVP (can be single fill per candle).

### Slippage

- Config: constant bps per symbol group (or per symbol)
- Optional: ATR-based

## Fees and funding

- Apply maker/taker rates per fill.
- Funding:
  - If holding crosses funding timestamp, apply funding cost/rebate based on configured rate time series.
  - MVP: allow constant funding rate per symbol (or use downloaded funding history later).

## Data requirements

- Candle series must be clean:
  - ordered timestamps
  - no duplicates
  - gap detection (mark and optionally fill)

## Outputs

- Trades ledger (fills + fees + funding)
- Equity curve and drawdown series
- Summary metrics:
  - net PnL
  - win rate
  - max drawdown
  - profit factor
  - average trade duration

