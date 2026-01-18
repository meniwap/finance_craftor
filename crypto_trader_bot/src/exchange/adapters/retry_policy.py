from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter


def default_retry():
    return retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=0.2, max=5.0),
        retry=retry_if_exception_type((TimeoutError, httpx.TimeoutException, httpx.TransportError)),
    )

