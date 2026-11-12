import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter with bounded bucket cleanup."""

    def __init__(self, max_buckets: int = 10000):
        self._buckets: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._max_buckets = max_buckets

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()

    def check(self, key: str, limit: int, window_seconds: int, detail: Optional[str] = None) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            if len(self._buckets) >= self._max_buckets:
                # Prune oldest expired keys so attacker IP rotation cannot exhaust RAM
                stale_keys = [k for k, dq in self._buckets.items() if not dq or dq[-1] < cutoff]
                for sk in stale_keys:
                    self._buckets.pop(sk, None)
                if len(self._buckets) >= self._max_buckets:
                    self._buckets.clear()

            dq = self._buckets.get(key)
            if dq is None:
                dq = deque()
                self._buckets[key] = dq

            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= limit:
                retry_after = max(1, int(window_seconds - (now - dq[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=detail or f"Too many requests. Please retry after {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )
            dq.append(now)

    def reset_key(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    """Resolve client IP cleanly behind reverse proxies while rejecting malformed headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first and len(first) <= 64:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"

