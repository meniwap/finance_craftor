from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlencode


@dataclass(frozen=True)
class ApiKeys:
    api_key: str
    api_secret: str


def load_keys_from_env() -> ApiKeys:
    k = os.environ.get("BINANCE_API_KEY", "").strip()
    s = os.environ.get("BINANCE_API_SECRET", "").strip()
    if not k or not s:
        raise RuntimeError(
            "Missing Binance API keys. Set BINANCE_API_KEY and BINANCE_API_SECRET in environment."
        )
    return ApiKeys(api_key=k, api_secret=s)


def sign_query(params: dict[str, str | int | float], api_secret: str) -> str:
    qs = urlencode(params, doseq=True)
    sig = hmac.new(api_secret.encode("utf-8"), qs.encode("utf-8"), sha256).hexdigest()
    return sig

