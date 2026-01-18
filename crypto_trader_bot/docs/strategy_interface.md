# Strategy Interface

## Purpose

Define a stable contract so strategies can be swapped without touching exchange / data / risk plumbing.

## Core concepts

### Context

`Context` is read-only for Strategy. It includes:

- Symbol + timeframe
- Latest candle + recent history window
- Indicator values (already computed)
- Fee/funding estimates snapshot
- Account/position state snapshot (read-only)
- Current risk state (e.g., halted, loss streak)
- Mode: backtest/paper/live

### Intent

Strategies emit a list of **Intents** describing *what they want*, not *how to do it*:

- Direction: LONG/SHORT (futures) or BUY/SELL (spot)
- Quantity intent (by notional or base qty) via a sizing policy
- Optional execution hints:
  - prefer_maker (bool)
  - time_in_force
  - max_slippage_bps
- Optional exit policy hints:
  - desired_tp, desired_sl, trailing parameters

The engine will pass Intents through:

1. Risk validation (allow/deny)
2. Fee/breakeven gating (deny if not net-profitable)
3. Execution policy translation into `OrderRequest` objects

## Strategy API

### Required method

- `on_candle(candle, context) -> list[Intent]`

### Optional hooks

- `on_fill(fill_event, context) -> list[Intent]` (e.g., place take-profit after entry fill)
- `on_funding(funding_event, context) -> list[Intent]` (rare; usually risk handles it)
- `on_start(context)` / `on_stop(context)` for lifecycle

## Guidelines

- Strategy must be **pure** relative to exchange IO (no REST/WS calls).
- Strategy may keep internal state, but it must be per-symbol (no global mutable state).
- Strategy must be robust to missing indicator values (warm-up period).

