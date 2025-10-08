"""Feature-gated API key authentication middleware."""

from __future__ import annotations

import hmac
from typing import Iterable

from fastapi import Request
from starlette.middleware.base import (BaseHTTPMiddleware,
                                       RequestResponseEndpoint)
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import SecurityConfig
from app.errors import ErrorCode, to_response
from app.logging import get_logger
from app.logging_events import log_event

_logger = get_logger(__name__)


def _is_allowlisted(path: str, allowlist: Iterable[str]) -> bool:
    for prefix in allowlist:
        if not prefix:
            continue
        if prefix == "/" and path == "/":
            return True
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def _extract_presented_key(request: Request) -> str | None:
    header_key = request.headers.get("X-API-Key", "").strip()
    if header_key:
        return header_key

    authorization = request.headers.get("Authorization", "")
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    scheme = scheme.lower()
    if scheme not in {"apikey", "bearer"}:
        return None
    candidate = value.strip()
    return candidate or None


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Validate API key credentials when authentication is enabled."""

    def __init__(self, app: ASGIApp, *, security: SecurityConfig) -> None:
        super().__init__(app)
        self._security = security

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        security_state = getattr(request.app.state, "security_config", self._security)
        if not security_state.resolve_require_auth():
            return await call_next(request)

        path = request.url.path
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        if _is_allowlisted(path, security_state.allowlist):
            return await call_next(request)

        if not security_state.api_keys:
            log_event(
                _logger,
                "auth.misconfigured",
                component="middleware.auth",
                status="error",
                path=path,
                method=request.method,
            )
            return to_response(
                message="An API key is required to access this resource.",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=401,
                request_path=path,
                method=request.method,
            )

        presented_key = _extract_presented_key(request)
        if not presented_key:
            log_event(
                _logger,
                "auth.missing",
                component="middleware.auth",
                status="error",
                path=path,
                method=request.method,
            )
            return to_response(
                message="An API key is required to access this resource.",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=401,
                request_path=path,
                method=request.method,
            )

        if not any(hmac.compare_digest(presented_key, key) for key in security_state.api_keys):
            log_event(
                _logger,
                "auth.invalid",
                component="middleware.auth",
                status="error",
                path=path,
                method=request.method,
            )
            return to_response(
                message="The provided API key is not valid.",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=403,
                request_path=path,
                method=request.method,
            )

        request.state.api_key = presented_key
        return await call_next(request)


__all__ = ["ApiKeyAuthMiddleware"]
