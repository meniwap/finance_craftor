# Futures risk notes (USDT-M)

## Modes and settings

### Margin mode

- **Isolated (default)**: per-position margin isolation. Safer for MVP.
- Cross: share margin across positions; easier to liquidate entire account if mismanaged.

### Position mode

- One-way (default): single net position per symbol.
- Hedge: long and short simultaneously per symbol (more complex accounting).

### Leverage

Enforce caps:

- per-symbol `max_leverage`
- portfolio-level effective leverage limit (exposure / equity)

## Liquidation distance guard

The bot must compute/obtain an approximation of liquidation price (or use exchange-provided if available),
then ensure a minimum distance to liquidation for any *new* exposure.

If distance to liquidation is below threshold:

- Block new entries
- Optionally reduce risk (reduceOnly market/limit)
- Trigger alerts and kill switch if severe

## Funding

- Funding occurs periodically (often every 8 hours) and can be a meaningful drag.
- Strategy decisions should include a funding estimate for the expected holding window.
- Risk may block trades that rely on tiny targets that funding can erase.

## Order flags and safety

- Use `reduceOnly` for exits (TP/SL) to avoid accidentally increasing exposure.
- Prefer explicit `positionSide` rules depending on one-way/hedge mode.
- For stops: ensure trigger price and limit price semantics are correct (Binance specifics differ by order type).

## Operational safety

- Manual kill switch must immediately:
  - cancel all open orders
  - prevent new order placement
  - optionally close positions depending on configured policy

