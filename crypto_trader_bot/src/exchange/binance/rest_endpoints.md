# Binance Futures (USDT-M) endpoints used

This doc lists the REST endpoints used by the codebase and why.

## Public

- `GET /fapi/v1/exchangeInfo`: symbol metadata (precision, filters, status)
- `GET /fapi/v1/ticker/24hr`: 24h stats for universe selection (quoteVolume)

## Signed

- `GET /fapi/v2/account`: balances / wallet info
- `GET /fapi/v2/positionRisk`: open positions, mark price, liquidation price
- `POST /fapi/v1/order`: place order
- `DELETE /fapi/v1/order`: cancel order

## User data stream

- `POST /fapi/v1/listenKey`: start user stream (requires API key header)
- `PUT /fapi/v1/listenKey`: keepalive

