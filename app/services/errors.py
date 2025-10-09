"""Shared error utilities for services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.core.transfers_api import TransfersApiError
from app.errors import AppError
from app.integrations.provider_gateway import (
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayInternalError,
    ProviderGatewayNotFoundError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
    ProviderGatewayValidationError,
)
from app.schemas.errors import ApiError, ErrorCode


@dataclass(slots=True)
class ServiceError(RuntimeError):
    """Exception raised by services when a request cannot be fulfilled."""

    api_error: ApiError

    def __str__(self) -> str:  # pragma: no cover - delegated to api_error
        return self.api_error.error.message


def _details_with_provider(
    provider: str | None, details: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if provider:
        payload["provider"] = provider
    if details:
        payload.update({key: value for key, value in details.items()})
    return payload or None


def to_api_error(exc: Exception, *, provider: str | None = None) -> ApiError:
    """Translate arbitrary exceptions into the canonical :class:`ApiError`."""

    if isinstance(exc, ServiceError):
        return exc.api_error
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, AppError):
        return ApiError.from_components(
            code=ErrorCode(exc.code.value),
            message=exc.message,
            details=_details_with_provider(provider, exc.meta),
        )
    if isinstance(exc, TransfersApiError):
        extra: dict[str, Any] | None = None
        if exc.details is not None:
            extra = dict(exc.details)
        if exc.status_code is not None:
            if extra is None:
                extra = {}
            extra.setdefault("status_code", exc.status_code)
        details = _details_with_provider(provider or "slskd", extra)
        return ApiError.from_components(
            code=ErrorCode(exc.code.value),
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayTimeoutError):
        details = _details_with_provider(
            provider or exc.provider,
            {"timeout_ms": exc.timeout_ms},
        )
        return ApiError.from_components(
            code=ErrorCode.DEPENDENCY_ERROR,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayRateLimitedError):
        extra: dict[str, Any] = {}
        if exc.retry_after_ms is not None:
            extra["retry_after_ms"] = exc.retry_after_ms
        if exc.retry_after_header is not None:
            extra["retry_after_header"] = exc.retry_after_header
        if exc.status_code is not None:
            extra["status_code"] = exc.status_code
        details = _details_with_provider(provider or exc.provider, extra)
        return ApiError.from_components(
            code=ErrorCode.RATE_LIMITED,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayValidationError):
        details = _details_with_provider(
            provider or exc.provider,
            {"status_code": exc.status_code} if exc.status_code is not None else None,
        )
        return ApiError.from_components(
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayNotFoundError):
        details = _details_with_provider(provider or exc.provider)
        return ApiError.from_components(
            code=ErrorCode.NOT_FOUND,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayDependencyError):
        details = _details_with_provider(
            provider or exc.provider,
            {"status_code": exc.status_code} if exc.status_code is not None else None,
        )
        return ApiError.from_components(
            code=ErrorCode.DEPENDENCY_ERROR,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayInternalError):
        details = _details_with_provider(provider or exc.provider)
        return ApiError.from_components(
            code=ErrorCode.DEPENDENCY_ERROR,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ProviderGatewayError):
        details = _details_with_provider(provider or exc.provider)
        return ApiError.from_components(
            code=ErrorCode.DEPENDENCY_ERROR,
            message=str(exc),
            details=details,
        )
    if isinstance(exc, ValueError):
        return ApiError.from_components(
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc) or "Invalid input provided.",
            details=_details_with_provider(provider),
        )
    return ApiError.from_components(
        code=ErrorCode.INTERNAL_ERROR,
        message=str(exc) or "Unexpected service error.",
        details=_details_with_provider(provider),
    )


__all__ = ["ServiceError", "to_api_error"]
