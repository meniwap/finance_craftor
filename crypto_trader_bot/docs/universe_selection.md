# Universe Selection (Multi-Symbol)

## Purpose

Binance has hundreds of symbols. The bot must decide which symbols are **active** to trade right now, balancing opportunity vs resource limits.

## Inputs

- Exchange symbol metadata: status, precision, step/tick size, min notional
- 24h stats: volume, quote volume, trade count
- Optional risk metadata: blacklist, cooldown, correlation buckets

## Modes

### ALL

Trade every symbol that passes filters. Not recommended for MVP.

### TOP-N (MVP)

Select top N symbols by `quoteVolume` for a chosen quote asset (e.g., USDT).

### ROTATION

Every `rotation_interval`, compute a score per symbol and pick top N.

Example scorers:

- Momentum (ROC over last X candles)
- Volatility (ATR or realized std)
- Liquidity (quote volume / spreads)

## Filters

Common filters:

- `quote_asset == USDT`
- `status == TRADING`
- min 24h quote volume
- exclude list (manual)
- optionally exclude leveraged tokens / weird contracts

## Registry

`UniverseRegistry` stores the current active set and symbol metadata:

- stepSize / tickSize / minNotional
- allowed leverage range
- contract type
- last refresh time

## Operational constraints

- Respect WS stream limits: aggregate subscriptions when possible.
- Respect REST rate limits: central limiter and backoff.
- Avoid thrashing: apply hysteresis so active set doesn’t change too often.

