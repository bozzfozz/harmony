"""Install the Harmony API middleware chain."""

from __future__ import annotations

import asyncio
import hmac
import math
import os
import time
from collections import deque
from typing import Deque

from fastapi import FastAPI, Request

from app.api.router_registry import compose_prefix
from app.config import AppConfig, SecurityConfig
from app.errors import AppError, ErrorCode, RateLimitedError
from app.logging import get_logger
from app.logging_events import log_event
from app.middleware.cache_conditional import CachePolicy, ConditionalCacheMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.services.cache import ResponseCache

_logger = get_logger(__name__)


class _RateLimiter:
    """Simple in-process rate limiter using a sliding time window."""

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: Deque[float] = deque(maxlen=max_requests)
        self._lock = asyncio.Lock()

    async def acquire(self) -> tuple[bool, float | None]:
        now = time.monotonic()
        async with self._lock:
            while self._timestamps and now - self._timestamps[0] > self._window_seconds:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._max_requests:
                retry_after = self._window_seconds - (now - self._timestamps[0])
                return False, max(0.0, retry_after)
            self._timestamps.append(now)
            return True, None


def _env_as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_as_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_as_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_cache_path(raw_path: str, base_prefix: str) -> str:
    path = raw_path.strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path}"
    if not base_prefix or base_prefix == "/":
        return path
    if path.startswith(base_prefix):
        return path
    return f"{base_prefix.rstrip('/')}{path}"


def _parse_cache_policies(
    raw_value: str | None,
    *,
    base_prefix: str,
    default_ttl: int,
    default_stale: int,
) -> dict[str, CachePolicy]:
    if not raw_value:
        return {}
    policies: dict[str, CachePolicy] = {}
    for chunk in raw_value.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        parts = [component.strip() for component in entry.split("|") if component.strip()]
        if not parts:
            continue
        path = _normalise_cache_path(parts[0], base_prefix)
        max_age = default_ttl
        stale = default_stale
        if len(parts) > 1:
            max_age = _env_as_int(parts[1], default=default_ttl)
        if len(parts) > 2:
            stale = _env_as_int(parts[2], default=default_stale)
        policies[path] = CachePolicy(
            path=path,
            max_age=max_age,
            stale_while_revalidate=stale,
        )
    return policies


def _is_allowlisted(path: str, allowlist: tuple[str, ...]) -> bool:
    for prefix in allowlist:
        if not prefix:
            continue
        if prefix == "/" and path == "/":
            return True
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def _extract_presented_key(request: Request) -> str | None:
    header_key = request.headers.get("X-API-Key")
    if header_key and header_key.strip():
        return header_key.strip()

    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header[7:].strip()
        if candidate:
            return candidate
    return None


def _install_cache_middleware(app: FastAPI, *, base_path: str) -> None:
    cache_enabled = _env_as_bool(os.getenv("CACHE_ENABLED"), default=True)
    cache_default_ttl = _env_as_int(os.getenv("CACHE_DEFAULT_TTL_S"), default=30)
    cache_default_stale = _env_as_int(
        os.getenv("CACHE_STALE_WHILE_REVALIDATE_S"), default=cache_default_ttl * 2
    )
    cache_max_items = _env_as_int(os.getenv("CACHE_MAX_ITEMS"), default=5_000)
    cache_fail_open = _env_as_bool(os.getenv("CACHE_FAIL_OPEN"), default=True)
    cache_etag_strategy = os.getenv("CACHE_STRATEGY_ETAG", "strong")
    cacheable_paths_raw = os.getenv("CACHEABLE_PATHS")

    response_cache = ResponseCache(
        max_items=cache_max_items,
        default_ttl=float(cache_default_ttl),
        fail_open=cache_fail_open,
    )
    app.state.response_cache = response_cache

    effective_base = compose_prefix("", base_path) or "/"
    cache_policies = _parse_cache_policies(
        cacheable_paths_raw,
        base_prefix=effective_base,
        default_ttl=cache_default_ttl,
        default_stale=cache_default_stale,
    )
    app.state.cache_policies = cache_policies

    default_policy = CachePolicy(
        path="*",
        max_age=cache_default_ttl,
        stale_while_revalidate=cache_default_stale,
    )

    app.add_middleware(
        ConditionalCacheMiddleware,
        cache=response_cache,
        default_policy=default_policy,
        policies=cache_policies,
        enabled=cache_enabled,
        etag_strategy=cache_etag_strategy,
        vary_headers=("Authorization", "X-API-Key", "Origin", "Accept-Encoding"),
    )


def install_api_middlewares(app: FastAPI, config: AppConfig, *, base_path: str = "") -> None:
    """Install request-id, logging, auth, rate limiting and cache middlewares."""

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    _install_cache_middleware(app, base_path=base_path)

    security_config = config.security

    rate_limiter: _RateLimiter | None = None
    if security_config.rate_limiting_enabled:
        max_requests = max(1, _env_as_int(os.getenv("RATE_LIMIT_MAX_REQUESTS"), default=120))
        window_seconds = max(1.0, _env_as_float(os.getenv("RATE_LIMIT_WINDOW_S"), default=60.0))
        rate_limiter = _RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
        app.state.rate_limiter = rate_limiter
    else:
        app.state.rate_limiter = None

    async def _apply_security(request: Request, call_next):  # type: ignore[override]
        security_state: SecurityConfig = getattr(
            request.app.state, "security_config", security_config
        )
        method = request.method.upper()
        path = request.url.path

        if method == "OPTIONS":
            return await call_next(request)

        is_allowlisted = _is_allowlisted(path, security_state.allowlist)

        if security_state.require_auth and not is_allowlisted:
            if not security_state.api_keys:
                _logger.warning(
                    "API key authentication enabled but no keys configured",  # pragma: no cover - logging string
                    extra={
                        "event": "auth.misconfigured",
                        "path": path,
                        "method": request.method,
                    },
                )
                error = AppError(
                    "An API key is required to access this resource.",
                    code=ErrorCode.INTERNAL_ERROR,
                    http_status=401,
                )
                return error.as_response(request_path=path, method=request.method)

            presented_key = _extract_presented_key(request)
            if not presented_key:
                _logger.warning(
                    "Missing API key for protected endpoint",  # pragma: no cover - logging string
                    extra={
                        "event": "auth.unauthorized",
                        "path": path,
                        "method": request.method,
                    },
                )
                error = AppError(
                    "An API key is required to access this resource.",
                    code=ErrorCode.INTERNAL_ERROR,
                    http_status=401,
                )
                return error.as_response(request_path=path, method=request.method)

            if not any(hmac.compare_digest(presented_key, key) for key in security_state.api_keys):
                _logger.warning(
                    "Invalid API key rejected",  # pragma: no cover - logging string
                    extra={
                        "event": "auth.forbidden",
                        "path": path,
                        "method": request.method,
                    },
                )
                error = AppError(
                    "The provided API key is not valid.",
                    code=ErrorCode.INTERNAL_ERROR,
                    http_status=403,
                )
                return error.as_response(request_path=path, method=request.method)

        limiter = getattr(request.app.state, "rate_limiter", rate_limiter)

        if security_state.rate_limiting_enabled and limiter is not None and not is_allowlisted:
            allowed, retry_after = await limiter.acquire()
            if not allowed:
                retry_header = None
                retry_after_ms = None
                if retry_after is not None:
                    retry_after_ms = int(retry_after * 1000)
                    retry_header = str(max(1, math.ceil(retry_after)))
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
                    retry_after_header=retry_header,
                )
                return error.as_response(request_path=path, method=request.method)

        return await call_next(request)

    app.middleware("http")(_apply_security)


__all__ = ["install_api_middlewares"]
