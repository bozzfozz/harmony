"""Application middleware registration helpers."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import AppConfig, get_env
from app.services.cache import ResponseCache

from .auth_apikey import ApiKeyAuthMiddleware
from .cache import CacheMiddleware
from .csp import ContentSecurityPolicyMiddleware
from .cors_gzip import install_cors_and_gzip
from .errors import setup_exception_handlers
from .logging import APILoggingMiddleware
from .rate_limit import RateLimitMiddleware
from .request_id import RequestIDMiddleware


def install_middleware(app: FastAPI, config: AppConfig) -> None:
    """Install the configured middleware stack on the provided application."""

    middleware_cfg = config.middleware

    allow_cdn = _as_bool(get_env("UI_ALLOW_CDN"))

    app.add_middleware(
        ContentSecurityPolicyMiddleware,
        allow_script_cdn=allow_cdn,
    )

    install_cors_and_gzip(app, cors=middleware_cfg.cors, gzip=middleware_cfg.gzip)

    response_cache = ResponseCache(
        max_items=middleware_cfg.cache.max_items,
        default_ttl=float(middleware_cfg.cache.default_ttl),
        fail_open=middleware_cfg.cache.fail_open,
        write_through=middleware_cfg.cache.write_through,
        log_evictions=middleware_cfg.cache.log_evictions,
    )
    app.state.response_cache = response_cache
    app.state.cache_write_through = middleware_cfg.cache.write_through
    app.state.cache_log_evictions = middleware_cfg.cache.log_evictions

    app.add_middleware(
        CacheMiddleware,
        cache=response_cache,
        config=middleware_cfg.cache,
    )

    app.add_middleware(ApiKeyAuthMiddleware, security=config.security)
    app.add_middleware(
        RateLimitMiddleware,
        config=middleware_cfg.rate_limit,
        security=config.security,
    )
    app.add_middleware(
        RequestIDMiddleware,
        header_name=middleware_cfg.request_id.header_name,
    )
    app.add_middleware(APILoggingMiddleware)

    setup_exception_handlers(app)


def _as_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["install_middleware"]
