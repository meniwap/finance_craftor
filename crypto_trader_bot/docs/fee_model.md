# Fee model (Trading fees + slippage + net breakeven)

## Trading fees

We model fees with:

- `maker_fee_rate` (e.g., 0.0002)
- `taker_fee_rate` (e.g., 0.0004)
- Optional BNB discount factor
- Optional VIP tier overrides

Fee cost estimate for a fill:

\n\(fee = notional * fee_rate\)\n

Where `notional = price * quantity`.

## Slippage

### Backtest/Paper

Use a configurable slippage model:

- constant bps: `slippage_bps`
- or ATR-based: `k * ATR/price`

### Live

Measure realized slippage from fills and keep a rolling estimate per symbol, then use it for gating.

## Net breakeven gating

Before submitting an entry intent, estimate:

- entry fee (taker unless maker confirmed)
- expected exit fee (often taker for stop / market exit)
- slippage on entry and exit
- funding estimate (if expected holding crosses funding timestamps)

Compute **net breakeven move**: minimal favorable price move required so that expected PnL after costs ≥ 0 (or ≥ configured minimum profit).

If strategy target profit is below breakeven threshold → deny the intent.

