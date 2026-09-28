import math
import logging
import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request

_lock = threading.Lock()
_counters: dict[tuple[str, str], tuple[int, int]] = {}
logger = logging.getLogger("eve.rate_limit")


def reset_rate_limits() -> None:
    """Reset counters, primarily for isolated tests."""
    with _lock:
        _counters.clear()


def rate_limit(scope: str, limit: int, window_seconds: int = 60) -> Callable:
    """Return a FastAPI dependency enforcing a per-client fixed-window request limit."""
    if limit < 1 or window_seconds < 1:
        raise ValueError("limit and window_seconds must be positive")

    def check_limit(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = int(now // window_seconds)
        key = (scope, client_ip)

        with _lock:
            previous_window, count = _counters.get(key, (window_start, 0))
            if previous_window != window_start:
                count = 0
            if count >= limit:
                retry_after = max(1, math.ceil((window_start + 1) * window_seconds - now))
                logger.warning("rate_limit_exceeded", extra={"event": "rate_limit_exceeded", "scope": scope})
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
            _counters[key] = (window_start, count + 1)

            if len(_counters) > 10_000:
                expired = [key for key, value in _counters.items() if value[0] != window_start]
                for expired_key in expired:
                    _counters.pop(expired_key, None)

    return check_limit
