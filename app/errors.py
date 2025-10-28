"""Unified error handling utilities for the Harmony API."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
import logging
from typing import Any
from uuid import uuid4

from fastapi import status
from fastapi.responses import JSONResponse

from app.config import get_env
from app.logging import get_logger


class ErrorCode(str, Enum):
    """Application level error codes exposed via the public API."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_logger = get_logger(__name__)


def _env_flag(name: str, *, default: bool) -> bool:
    raw = get_env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_FEATURE_ENABLED = _env_flag("FEATURE_UNIFIED_ERROR_FORMAT", default=True)
_DEBUG_DETAILS = _env_flag("ERRORS_DEBUG_DETAILS", default=False)


class AppError(Exception):
    """Base exception for Harmony specific API errors."""

    __slots__ = ("message", "code", "http_status", "meta", "headers")

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        meta: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.meta = meta
        self.headers = headers

    def as_response(self, *, request_path: str, method: str) -> JSONResponse:
        """Serialise the exception into the canonical error envelope."""

        return _build_response(
            message=self.message,
            code=self.code,
            status_code=self.http_status,
            request_path=request_path,
            method=method,
            meta=self.meta,
            headers=self.headers,
        )


class ValidationAppError(AppError):
    """Error raised when a client submitted invalid input."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            http_status=status_code,
            meta=meta,
        )


class AuthenticationRequiredError(AppError):
    """Error raised when authentication credentials are missing or invalid."""

    def __init__(
        self,
        message: str = "Authentication credentials are required.",
        *,
        status_code: int = status.HTTP_401_UNAUTHORIZED,
        meta: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if headers is None and status_code == status.HTTP_401_UNAUTHORIZED:
            headers = {"WWW-Authenticate": "APIKey"}
        super().__init__(
            message=message,
            code=ErrorCode.AUTH_REQUIRED,
            http_status=status_code,
            meta=meta,
            headers=headers,
        )


class NotFoundError(AppError):
    """Error raised when a resource could not be located."""

    def __init__(self, message: str = "Resource not found.") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.NOT_FOUND,
            http_status=status.HTTP_404_NOT_FOUND,
        )


class RateLimitedError(AppError):
    """Error raised when the client exceeded rate limits."""

    def __init__(
        self,
        message: str = "Too many requests.",
        *,
        retry_after_ms: int | None = None,
        retry_after_header: str | None = None,
    ) -> None:
        meta: dict[str, Any] | None = None
        if retry_after_ms is not None:
            meta = {"retry_after_ms": max(0, retry_after_ms)}
        headers: dict[str, str] | None = None
        if retry_after_header:
            headers = {"Retry-After": retry_after_header}
        super().__init__(
            message=message,
            code=ErrorCode.RATE_LIMITED,
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
            meta=meta,
            headers=headers,
        )


class DependencyError(AppError):
    """Error raised when upstream dependencies are unavailable."""

    def __init__(
        self,
        message: str = "Upstream service is unavailable.",
        *,
        status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.DEPENDENCY_ERROR,
            http_status=status_code,
            meta=meta,
        )


class InternalServerError(AppError):
    """Error raised when the application encountered an unexpected failure."""

    def __init__(self, message: str = "An unexpected error occurred.") -> None:
        super().__init__(
            message=message,
            code=ErrorCode.INTERNAL_ERROR,
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _copy_meta(meta: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    return dict(meta)


def _log_level_for_status(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code in {status.HTTP_429_TOO_MANY_REQUESTS, 424, 502, 503, 504}:
        return logging.WARNING
    return logging.INFO


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        seconds = int(value)
        return max(0, seconds * 1000)
    except (TypeError, ValueError):
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = parsed - datetime.now(UTC)
    milliseconds = int(delta.total_seconds() * 1000)
    return max(0, milliseconds)


def rate_limit_meta(
    headers: Mapping[str, str] | None,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Extract retry hints from rate limit headers."""

    if not headers:
        return None, {}
    retry_after: Any | None = None
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() == "retry-after":
            retry_after = value
            break
    retry_after_ms = _parse_retry_after(retry_after)
    meta: dict[str, Any] | None = None
    if retry_after_ms is not None:
        meta = {"retry_after_ms": retry_after_ms}
    response_headers: dict[str, str] = {}
    if retry_after is not None and retry_after != "":
        response_headers["Retry-After"] = str(retry_after)
    return meta, response_headers


def _build_response(
    *,
    message: str,
    code: ErrorCode,
    status_code: int,
    request_path: str,
    method: str,
    meta: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    debug_id = uuid4().hex

    if not _FEATURE_ENABLED:
        response = JSONResponse(status_code=status_code, content={"detail": message})
    else:
        safe_meta = _copy_meta(meta)
        if _DEBUG_DETAILS:
            if safe_meta is None:
                safe_meta = {}
            safe_meta.setdefault("debug_id", debug_id)
            safe_meta.setdefault("hint", "Provide the debug_id when contacting support.")

        payload: MutableMapping[str, Any] = {
            "ok": False,
            "error": {"code": code.value, "message": message},
        }
        if safe_meta:
            payload["error"]["meta"] = safe_meta

        response = JSONResponse(status_code=status_code, content=payload)

    response.headers["X-Debug-Id"] = debug_id
    if headers:
        for name, value in headers.items():
            response.headers[name] = value

    log_level = _log_level_for_status(status_code)
    _logger.log(
        log_level,
        "API request failed",  # pragma: no cover - logging string
        extra={
            "event": "api.error",
            "code": code.value,
            "status": status_code,
            "path": request_path,
            "method": method,
            "debug_id": debug_id,
        },
    )
    return response


def to_response(
    *,
    message: str,
    code: ErrorCode,
    status_code: int,
    request_path: str,
    method: str,
    meta: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Create an error response with the standard envelope."""

    return _build_response(
        message=message,
        code=code,
        status_code=status_code,
        request_path=request_path,
        method=method,
        meta=meta,
        headers=headers,
    )


__all__ = [
    "AuthenticationRequiredError",
    "AppError",
    "DependencyError",
    "ErrorCode",
    "InternalServerError",
    "NotFoundError",
    "RateLimitedError",
    "ValidationAppError",
    "rate_limit_meta",
    "to_response",
]
