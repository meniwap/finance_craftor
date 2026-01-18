from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from src.core.config import ExchangeConfig
from src.core.types import (
    Balance,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    Side,
)
from src.exchange.adapters.auth import ApiKeys, sign_query
from src.exchange.adapters.rate_limiter import SimpleRateLimiter
from src.exchange.adapters.retry_policy import default_retry
from src.exchange.base import ExchangeClient


class BinanceFuturesUsdtmClient(ExchangeClient):
    def __init__(
        self,
        cfg: ExchangeConfig,
        keys: ApiKeys,
        limiter: SimpleRateLimiter | None = None,
    ) -> None:
        self._cfg = cfg
        self._keys = keys
        self._limiter = limiter or SimpleRateLimiter()
        self._http = httpx.AsyncClient(base_url=cfg.base_url, timeout=10.0)
        self._time_offset_ms: int = 0
        self._log = logging.getLogger("binance")
        self._last_time_sync_ms: int = 0

    async def close(self) -> None:
        await self._http.aclose()

    @default_retry()
    async def _request(
        self,
        method: str,
        path: str,
        *,
        signed: bool = False,
        params: dict[str, Any] | None = None,
    ) -> Any:
        # note: tenacity retries only on transport/timeouts by default
        # (see adapters/retry_policy.py)
        await self._limiter.acquire()
        params = dict(params or {})

        headers = {"X-MBX-APIKEY": self._keys.api_key} if signed or path.endswith("listenKey") else {}

        def _normalize_items(d: dict[str, Any]) -> list[tuple[str, str]]:
            items: list[tuple[str, str]] = []
            for k, v in d.items():
                if v is None:
                    continue
                if isinstance(v, bool):
                    sv = "true" if v else "false"
                else:
                    sv = str(v)
                items.append((str(k), sv))
            return items

        for attempt in range(2):
            request_params: Any = params
            if signed:
                await self._maybe_sync_time()
                base = dict(params)
                base.pop("signature", None)
                base["timestamp"] = int(time.time() * 1000) + int(self._time_offset_ms)
                base["recvWindow"] = self._cfg.recv_window_ms

                # IMPORTANT: sign and send the exact same ordered querystring
                items = _normalize_items(base)
                qs = urlencode(items, doseq=True)
                # compute signature from the *same* querystring we will send
                import hmac
                from hashlib import sha256

                sig = hmac.new(self._keys.api_secret.encode("utf-8"), qs.encode("utf-8"), sha256).hexdigest()
                items.append(("signature", sig))
                request_params = items

            r = await self._http.request(method, path, params=request_params, headers=headers)
            if r.status_code < 400:
                return r.json()

            # Binance typically returns JSON: {"code": ..., "msg": "..."}
            code = None
            msg = None
            try:
                err = r.json()
                code = err.get("code")
                msg = err.get("msg")
            except Exception:
                msg = r.text

            # Handle time drift: -1021 (timestamp outside recvWindow)
            if signed and code == -1021 and attempt == 0:
                await self._sync_time(force=True)
                continue

            raise RuntimeError(f"Binance API error: http={r.status_code} code={code} msg={msg}")

        raise RuntimeError("Binance API error: failed after retry loop")

    async def _maybe_sync_time(self) -> None:
        now = int(time.time() * 1000)
        # refresh offset every ~10 minutes
        if self._last_time_sync_ms == 0 or (now - self._last_time_sync_ms) > 10 * 60 * 1000:
            await self._sync_time(force=True)

    async def _sync_time(self, force: bool = False) -> None:
        _ = force
        await self._limiter.acquire()
        r = await self._http.get("/fapi/v1/time")
        r.raise_for_status()
        server_time = int(r.json()["serverTime"])
        local_time = int(time.time() * 1000)
        self._time_offset_ms = server_time - local_time
        self._last_time_sync_ms = local_time

    async def fetch_exchange_info(self) -> dict[str, Any]:
        return await self._request("GET", "/fapi/v1/exchangeInfo")

    async def fetch_24h_tickers(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/fapi/v1/ticker/24hr")
        if isinstance(data, list):
            return data
        return [data]

    async def fetch_klines(self, symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
        data = await self._request(
            "GET",
            "/fapi/v1/klines",
            signed=False,
            params={"symbol": symbol, "interval": interval, "limit": int(limit)},
        )
        return data

    async def fetch_balances(self) -> list[Balance]:
        data = await self._request("GET", "/fapi/v2/account", signed=True)
        out: list[Balance] = []
        for b in data.get("assets", []):
            out.append(
                Balance(
                    asset=b.get("asset", ""),
                    available=float(b.get("availableBalance", 0.0)),
                    total=float(b.get("walletBalance", 0.0)),
                    update_time=datetime.now(timezone.utc),
                )
            )
        return out

    async def fetch_positions(self) -> list[Position]:
        data = await self._request("GET", "/fapi/v2/positionRisk", signed=True)
        out: list[Position] = []
        for p in data:
            qty = float(p.get("positionAmt", 0.0))
            if abs(qty) < 1e-9:
                continue
            entry = float(p.get("entryPrice", 0.0))
            mark = float(p.get("markPrice", 0.0))
            liq = float(p.get("liquidationPrice", 0.0)) if p.get("liquidationPrice") else None
            out.append(
                Position(
                    symbol=p.get("symbol", ""),
                    position_side=(PositionSide.LONG if qty > 0 else PositionSide.SHORT),
                    quantity=abs(qty),
                    entry_price=entry,
                    mark_price=mark,
                    unrealized_pnl=float(p.get("unRealizedProfit", 0.0)),
                    leverage=int(float(p.get("leverage", 0) or 0)) or None,
                    liquidation_price=liq,
                    update_time=datetime.now(timezone.utc),
                )
            )
        return out

    async def place_order(self, req: OrderRequest) -> Order:
        is_conditional = req.order_type in {
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.STOP,
            OrderType.TAKE_PROFIT,
        }

        def _build_order_params() -> dict[str, Any]:
            params: dict[str, Any] = {
                "symbol": req.symbol,
                "side": req.side.value,
                "type": req.order_type.value,
                "newOrderRespType": "RESULT",
            }
            extra = req.meta.get("extra_params") if isinstance(req.meta, dict) else None
            if isinstance(extra, dict):
                params.update(extra)
            close_position = str(params.get("closePosition", "false")).lower() in {"true", "1", "yes"}
            if not close_position:
                params["quantity"] = f"{req.quantity:.8f}"
            if req.price is not None:
                params["price"] = f"{req.price:.8f}"
            if req.stop_price is not None:
                params["stopPrice"] = f"{req.stop_price:.8f}"
            if req.time_in_force is not None:
                params["timeInForce"] = req.time_in_force.value
            if req.reduce_only:
                params["reduceOnly"] = "true"
            if req.client_order_id:
                params["newClientOrderId"] = req.client_order_id
            return params

        def _build_algo_params() -> dict[str, Any]:
            params: dict[str, Any] = {
                "algoType": "CONDITIONAL",
                "symbol": req.symbol,
                "side": req.side.value,
                "type": req.order_type.value,
            }
            extra = req.meta.get("extra_params") if isinstance(req.meta, dict) else None
            if isinstance(extra, dict):
                params.update(extra)
            if req.stop_price is not None:
                params["triggerPrice"] = f"{req.stop_price:.8f}"
            if req.price is not None:
                params["price"] = f"{req.price:.8f}"
            if req.time_in_force is not None:
                params["timeInForce"] = req.time_in_force.value
            if req.reduce_only:
                params["reduceOnly"] = "true"
            if req.quantity > 0:
                params["quantity"] = f"{req.quantity:.8f}"
            if req.client_order_id:
                params["clientAlgoId"] = req.client_order_id
            return params

        try:
            data = await self._request("POST", "/fapi/v1/order", signed=True, params=_build_order_params())
        except Exception as e:
            msg = str(e)
            if is_conditional and "code=-4120" in msg:
                self._log.warning("Fallback to algoOrder for %s %s: %s", req.symbol, req.order_type.value, msg)
                data = await self._request("POST", "/fapi/v1/algoOrder", signed=True, params=_build_algo_params())
            else:
                raise
        avg_price = float(data.get("avgPrice", 0.0) or 0.0)
        price_val = float(data.get("price", 0.0) or 0.0)
        effective_price = avg_price if (req.order_type == OrderType.MARKET and avg_price > 0) else price_val
        order_id = str(data.get("orderId") or data.get("algoId") or data.get("clientAlgoId") or data.get("clientOrderId") or "unknown")
        return Order(
            order_id=order_id,
            client_order_id=data.get("clientOrderId"),
            symbol=data.get("symbol", req.symbol),
            side=Side(data.get("side", req.side.value)),
            order_type=OrderType(data.get("type", req.order_type.value)),
            status=OrderStatus(data.get("status", OrderStatus.NEW.value)),
            price=effective_price if effective_price else req.price,
            orig_qty=float(data.get("origQty", req.quantity)),
            executed_qty=float(data.get("executedQty", 0.0)),
            update_time=datetime.now(timezone.utc),
            reduce_only=req.reduce_only,
            meta={"raw": data},
        )

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        await self._request("DELETE", "/fapi/v1/order", signed=True, params={"symbol": symbol, "orderId": order_id})

    async def cancel_all_open_orders(self, symbol: str) -> None:
        await self._request("DELETE", "/fapi/v1/allOpenOrders", signed=True, params={"symbol": symbol})

    async def cancel_all_open_algo_orders(self, symbol: str) -> None:
        # Cancel All Algo Open Orders(TRADE): DELETE /fapi/v1/algoOpenOrders
        await self._request("DELETE", "/fapi/v1/algoOpenOrders", signed=True, params={"symbol": symbol})

    async def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        return await self._request("GET", "/fapi/v1/openOrders", signed=True, params={"symbol": symbol})

    async def fetch_open_algo_orders(self, symbol: str) -> list[dict[str, Any]]:
        return await self._request("GET", "/fapi/v1/openAlgoOrders", signed=True, params={"symbol": symbol})

    async def cancel_algo_order(self, algo_id: int) -> None:
        await self._request("DELETE", "/fapi/v1/algoOrder", signed=True, params={"algoId": int(algo_id)})

    async def start_user_stream(self) -> str:
        # For futures: POST /fapi/v1/listenKey with APIKEY header
        await self._limiter.acquire()
        r = await self._http.post(
            "/fapi/v1/listenKey",
            headers={"X-MBX-APIKEY": self._keys.api_key},
        )
        r.raise_for_status()
        return r.json()["listenKey"]

    async def keepalive_user_stream(self, listen_key: str) -> None:
        await self._limiter.acquire()
        r = await self._http.put(
            "/fapi/v1/listenKey",
            params={"listenKey": listen_key},
            headers={"X-MBX-APIKEY": self._keys.api_key},
        )
        r.raise_for_status()

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        data = await self._request(
            "POST",
            "/fapi/v1/leverage",
            signed=True,
            params={"symbol": symbol, "leverage": int(leverage)},
        )
        # Binance responds with {"leverage": 20, ...}
        return int(data.get("leverage", leverage))

    async def fetch_max_leverage(self, symbol: str) -> int | None:
        """
        Return maximum allowed leverage for a symbol using /fapi/v1/leverageBracket.
        """
        data = await self._request("GET", "/fapi/v1/leverageBracket", signed=True, params={"symbol": symbol})
        # Response is typically a list with one element per symbol
        if isinstance(data, list) and data:
            item = data[0] or {}
        elif isinstance(data, dict):
            item = data
        else:
            return None
        brackets = item.get("brackets") or []
        max_lev = 0
        for b in brackets:
            try:
                max_lev = max(max_lev, int(float(b.get("initialLeverage", 0) or 0)))
            except Exception:
                continue
        return max_lev or None

