"""Feature-gated token bucket rate limiting middleware."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import RateLimitMiddlewareConfig, SecurityConfig
from app.errors import RateLimitedError
from app.logging import get_logger
from app.logging_events import log_event

from .auth_apikey import _extract_presented_key, _is_allowlisted

_logger = get_logger(__name__)


@dataclass(slots=True)
class _TokenBucket:
    capacity: int
    refill_per_second: float
    tokens: float
    last_checked: float

    def acquire(self, *, now: float) -> tuple[bool, float]:
        if self.refill_per_second > 0:
            elapsed = max(0.0, now - self.last_checked)
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.last_checked = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0.0
        deficit = 1.0 - self.tokens
        if self.refill_per_second <= 0:
            return False, float("inf")
        wait_seconds = deficit / self.refill_per_second
        return False, max(0.0, wait_seconds)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-identity token bucket rate limiting when enabled."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: RateLimitMiddlewareConfig,
        security: SecurityConfig,
    ) -> None:
        super().__init__(app)
        self._config = config
        self._security = security
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = asyncio.Lock()

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        security_state = getattr(request.app.state, "security_config", self._security)
        enabled = bool(getattr(security_state, "rate_limiting_enabled", False))
        if not enabled:
            return await call_next(request)

        path = request.url.path
        if _is_allowlisted(path, security_state.allowlist):
            return await call_next(request)

        limiter = getattr(request.app.state, "rate_limiter", None)
        override_capacity: int | None = None
        override_refill: float | None = None
        if limiter is not None:
            max_requests = getattr(limiter, "_max_requests", None)
            window_seconds = getattr(limiter, "_window_seconds", None)
            if max_requests and window_seconds and window_seconds > 0:
                override_capacity = int(max(1, max_requests))
                override_refill = override_capacity / float(window_seconds)

        identity = self._build_identity(request)
        allowed, retry_after = await self._take_token(
            identity,
            capacity=override_capacity,
            refill=override_refill,
        )
        if not allowed:
            retry_after_ms: int | None
            retry_after_header: str
            if math.isinf(retry_after):
                retry_after_ms = None
                retry_after_header = "1"
            else:
                retry_after_ms = int(max(0.0, retry_after) * 1000)
                retry_after_header = str(max(1, math.ceil(retry_after))) if retry_after > 0 else "1"

            log_event(
                _logger,
                "api.rate_limited",
                component="middleware.rate_limit",
                status="error",
                path=path,
                method=request.method,
                entity_id=getattr(request.state, "request_id", None),
                meta={"retry_after_ms": retry_after_ms} if retry_after_ms is not None else None,
            )
            error = RateLimitedError(
                retry_after_ms=retry_after_ms,
                retry_after_header=retry_after_header,
            )
            return error.as_response(request_path=path, method=request.method)

        return await call_next(request)

    def _is_enabled(self, request: Request) -> bool:
        security_state = getattr(request.app.state, "security_config", self._security)
        return bool(getattr(security_state, "rate_limiting_enabled", False))

    def _build_identity(self, request: Request) -> str:
        client_host = "unknown"
        if request.client and request.client.host:
            client_host = request.client.host
        api_key = (
            getattr(request.state, "api_key", None) or _extract_presented_key(request) or "anon"
        )
        route = request.scope.get("route")
        path_template = getattr(route, "path_format", request.url.path)
        return f"{client_host}|{api_key}|{path_template}"

    async def _take_token(
        self,
        identity: str,
        *,
        capacity: int | None = None,
        refill: float | None = None,
    ) -> tuple[bool, float]:
        bucket_capacity = max(1, capacity or self._config.bucket_capacity)
        refill_rate = self._config.refill_per_second if refill is None else max(0.0, refill)
        key = f"{identity}|{bucket_capacity}|{refill_rate}"
        async with self._lock:
            bucket = self._buckets.get(key)
            now = time.monotonic()
            if bucket is None:
                bucket = _TokenBucket(
                    capacity=bucket_capacity,
                    refill_per_second=refill_rate,
                    tokens=float(bucket_capacity),
                    last_checked=now,
                )
                self._buckets[key] = bucket
            allowed, retry_after = bucket.acquire(now=now)
            return allowed, retry_after


__all__ = ["RateLimitMiddleware"]
