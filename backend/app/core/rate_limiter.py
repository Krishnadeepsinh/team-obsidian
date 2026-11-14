import ipaddress
import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger("obsidian.ratelimit")


class SlidingWindowRateLimiter:
    """Thread-safe DB-backed sliding-window rate limiter with per-key locking and in-memory fallback."""

    def __init__(self, max_buckets: int = 10000):
        self._buckets: Dict[str, Deque[float]] = {}
        self._key_locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        self._max_buckets = max_buckets

    def _get_key_lock(self, key: str) -> threading.Lock:
        with self._global_lock:
            if key not in self._key_locks:
                if len(self._key_locks) >= self._max_buckets:
                    self._key_locks.clear()
                self._key_locks[key] = threading.Lock()
            return self._key_locks[key]

    def clear_memory_only(self) -> None:
        """Clear only in-memory L1 buckets without removing persisted DB events."""
        with self._global_lock:
            self._buckets.clear()
            self._key_locks.clear()

    def clear(self, clear_db: bool = True) -> None:
        """Reset rate-limit state in memory and optionally purge persisted DB events."""
        from app.models.workspace import RateLimitEvent

        with self._global_lock:
            self._buckets.clear()
            self._key_locks.clear()
        if clear_db:
            session = SessionLocal()
            try:
                session.query(RateLimitEvent).delete(synchronize_session=False)
                session.commit()
            except SQLAlchemyError as exc:
                logger.warning("Failed to clear rate_limit_events table: %s", exc)
                session.rollback()
            finally:
                session.close()

    def _record_memory_fallback(self, key: str, limit: int, window_seconds: int, now: float, detail: Optional[str]) -> None:
        key_lock = self._get_key_lock(key)
        with key_lock:
            cutoff = now - window_seconds
            with self._global_lock:
                if len(self._buckets) >= self._max_buckets:
                    stale_keys = [k for k, dq in self._buckets.items() if not dq or dq[-1] < cutoff]
                    for sk in stale_keys:
                        self._buckets.pop(sk, None)
                    if len(self._buckets) >= self._max_buckets:
                        self._buckets.clear()

                dq = self._buckets.setdefault(key, deque())

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

    def check(self, key: str, limit: int, window_seconds: int, detail: Optional[str] = None) -> None:
        from app.models.workspace import RateLimitEvent

        now = time.time()
        cutoff = now - window_seconds

        # Database I/O is performed without a global lock to prevent concurrency bottlenecks
        session = SessionLocal()
        try:
            session.query(RateLimitEvent).filter(
                RateLimitEvent.bucket_key == key,
                RateLimitEvent.created_ts < cutoff,
            ).delete(synchronize_session=False)

            active = (
                session.query(RateLimitEvent.created_ts)
                .filter(
                    RateLimitEvent.bucket_key == key,
                    RateLimitEvent.created_ts >= cutoff,
                )
                .order_by(RateLimitEvent.created_ts.asc())
                .all()
            )
            if len(active) >= limit:
                oldest = float(active[0][0])
                retry_after = max(1, int(window_seconds - (now - oldest)))
                session.commit()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=detail or f"Too many requests. Please retry after {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )

            session.add(RateLimitEvent(bucket_key=key, created_ts=now))
            session.commit()

            key_lock = self._get_key_lock(key)
            with key_lock:
                dq = self._buckets.setdefault(key, deque())
                while dq and dq[0] < cutoff:
                    dq.popleft()
                dq.append(now)
        except HTTPException:
            raise
        except SQLAlchemyError as exc:
            logger.warning("Falling back to in-memory rate limiter due to DB error: %s", exc)
            session.rollback()
            self._record_memory_fallback(key, limit, window_seconds, now, detail)
        finally:
            session.close()

    def reset_key(self, key: str) -> None:
        from app.models.workspace import RateLimitEvent

        key_lock = self._get_key_lock(key)
        with key_lock:
            with self._global_lock:
                self._buckets.pop(key, None)
        session = SessionLocal()
        try:
            session.query(RateLimitEvent).filter(RateLimitEvent.bucket_key == key).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:
            logger.warning("Failed to reset rate limit key '%s': %s", key, exc)
            session.rollback()
        finally:
            session.close()


rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    """Resolve client IP cleanly behind trusted reverse proxies; rejects spoofed X-Forwarded-For from untrusted clients."""
    client_host = request.client.host if request.client else ""
    trusted_proxies = set(getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1", "localhost", "testclient"]))

    is_trusted_proxy = False
    if client_host:
        if client_host in trusted_proxies or client_host.startswith("127.") or client_host == "::1":
            is_trusted_proxy = True
        else:
            try:
                ip = ipaddress.ip_address(client_host)
                if ip.is_private or ip.is_loopback:
                    is_trusted_proxy = True
            except ValueError:
                pass

    # Only trust X-Forwarded-For if the immediate connection is from a trusted reverse proxy
    if is_trusted_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            valid_hops = []
            for h in hops:
                try:
                    ipaddress.ip_address(h)
                    valid_hops.append(h)
                except ValueError:
                    continue
            if valid_hops:
                idx = max(0, len(valid_hops) - max(1, settings.TRUSTED_PROXY_HOPS))
                return valid_hops[idx]

    if client_host:
        return client_host
    return "unknown"

