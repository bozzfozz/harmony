"""Compatibility shims for legacy middleware imports."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Deque

from app.middleware import install_middleware

__all__ = ["install_middleware", "_RateLimiter"]


class _RateLimiter:
    """Legacy in-process rate limiter used by older tests."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: Deque[float] = deque(maxlen=max_requests)
        self._lock = asyncio.Lock()

    async def acquire(self) -> tuple[bool, float | None]:
        now = time.monotonic()
        async with self._lock:
            self._evict_expired(now)
            if len(self._timestamps) >= self._max_requests:
                retry_after = self._window_seconds - (now - self._timestamps[0])
                return False, max(0.0, retry_after)
            self._timestamps.append(now)
            return True, None

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()
