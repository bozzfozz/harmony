"""Helpers for mapping provider gateway errors to application-level errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, MutableMapping, Type

from app.errors import (
    DependencyError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.integrations.provider_gateway import (
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayInternalError,
    ProviderGatewayNotFoundError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
    ProviderGatewayValidationError,
)


@dataclass(slots=True, frozen=True)
class _ErrorMapping:
    """Describe how a gateway error should be converted."""

    factory: Callable[[str, ProviderGatewayError], Exception]


def _validation_error(provider: str, error: ProviderGatewayError) -> ValidationAppError:
    status = getattr(error, "status_code", None)
    meta: MutableMapping[str, object] = {}
    if status is not None:
        meta["provider_status"] = status
    return ValidationAppError(f"{provider} rejected the search request.", meta=meta or None)


def _rate_limited_error(provider: str, error: ProviderGatewayError) -> RateLimitedError:
    retry_ms = getattr(error, "retry_after_ms", None)
    retry_header = getattr(error, "retry_after_header", None)
    return RateLimitedError(
        f"{provider} rate limited the search request.",
        retry_after_ms=retry_ms,
        retry_after_header=retry_header,
    )


def _not_found_error(provider: str, error: ProviderGatewayError) -> NotFoundError:
    return NotFoundError(f"{provider} returned no matching results.")


def _timeout_error(provider: str, error: ProviderGatewayError) -> DependencyError:
    timeout_ms = getattr(error, "timeout_ms", None)
    meta: MutableMapping[str, object] = {}
    if timeout_ms is not None:
        meta["timeout_ms"] = timeout_ms
    return DependencyError(f"{provider} search timed out.", meta=meta or None)


def _dependency_error(provider: str, error: ProviderGatewayError) -> DependencyError:
    status = getattr(error, "status_code", None)
    meta: MutableMapping[str, object] = {}
    if status is not None:
        meta["provider_status"] = status
    return DependencyError(f"{provider} search is currently unavailable.", meta=meta or None)


def _internal_error(provider: str, error: ProviderGatewayError) -> InternalServerError:
    return InternalServerError(f"Failed to process {provider} search results.")


_ERROR_MAP: Mapping[Type[ProviderGatewayError], _ErrorMapping] = {
    ProviderGatewayValidationError: _ErrorMapping(factory=_validation_error),
    ProviderGatewayRateLimitedError: _ErrorMapping(factory=_rate_limited_error),
    ProviderGatewayNotFoundError: _ErrorMapping(factory=_not_found_error),
    ProviderGatewayTimeoutError: _ErrorMapping(factory=_timeout_error),
    ProviderGatewayDependencyError: _ErrorMapping(factory=_dependency_error),
    ProviderGatewayInternalError: _ErrorMapping(factory=_internal_error),
}


def to_application_error(provider: str, error: ProviderGatewayError) -> Exception:
    """Return an application level error for the given gateway error."""

    for error_type, mapping in _ERROR_MAP.items():
        if isinstance(error, error_type):
            return mapping.factory(provider, error)
    return InternalServerError(f"Unexpected error during {provider} search.")


__all__ = ["to_application_error"]
