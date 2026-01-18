# Indicator Interface

## Purpose

Indicators are standalone components that compute derived values from candles/prices. They do **not** decide trades.

## Indicator API

### Required method

- `compute(candles) -> IndicatorResult`

Where `candles` is an ordered window (oldest → newest).

### IndicatorResult

Indicator output contains:

- `values`: numeric series or latest value (depending on indicator)
- `state`: optional normalized state (e.g., overbought/oversold)
- `meta`: parameters, warm-up length, missing-data flags

## Signal rules

Signal rules translate IndicatorResult into trading-relevant **Signals**:

- Input: one or more IndicatorResults
- Output: `BUY` / `SELL` / `NEUTRAL` (or `LONG` / `SHORT` / `NEUTRAL` depending on internal normalization)

Rules are independent modules so you can reuse the same indicator with multiple rule interpretations:

- RSI threshold rule: RSI < 30 → BUY, RSI > 70 → SELL
- Crossover rule: EMA_fast crosses above EMA_slow → BUY

## Testing

Each indicator must support deterministic unit tests:

- Use fixed candle fixtures (CSV)
- Assert known outputs for chosen parameters
- Validate warm-up behavior (insufficient candles → `is_ready=False`)


