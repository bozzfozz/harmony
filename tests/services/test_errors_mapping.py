from __future__ import annotations

from app.errors import DependencyError, ValidationAppError
from app.integrations.provider_gateway import (
    ProviderGatewayDependencyError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
)
from app.services.errors import ServiceError, to_api_error


def test_to_api_error_preserves_service_error() -> None:
    original = ServiceError(
        api_error=to_api_error(ValidationAppError("bad input")),
    )
    mapped = to_api_error(original)
    assert mapped == original.api_error


def test_to_api_error_from_app_error() -> None:
    app_error = DependencyError("dependency down")
    mapped = to_api_error(app_error, provider="spotify")
    assert mapped.error.code == "DEPENDENCY_ERROR"
    assert mapped.error.details == {"provider": "spotify"}


def test_to_api_error_from_timeout() -> None:
    exc = ProviderGatewayTimeoutError("spotify", timeout_ms=1500)
    mapped = to_api_error(exc)
    assert mapped.error.code == "DEPENDENCY_ERROR"
    assert mapped.error.details == {"provider": "spotify", "timeout_ms": 1500}


def test_to_api_error_from_rate_limited() -> None:
    exc = ProviderGatewayRateLimitedError(
        "spotify",
        retry_after_ms=5000,
        retry_after_header="5",
        status_code=429,
    )
    mapped = to_api_error(exc)
    assert mapped.error.code == "RATE_LIMITED"
    assert mapped.error.details == {
        "provider": "spotify",
        "retry_after_ms": 5000,
        "retry_after_header": "5",
        "status_code": 429,
    }


def test_to_api_error_from_dependency_error() -> None:
    exc = ProviderGatewayDependencyError("slskd", status_code=503)
    mapped = to_api_error(exc)
    assert mapped.error.code == "DEPENDENCY_ERROR"
    assert mapped.error.details == {"provider": "slskd", "status_code": 503}


def test_to_api_error_from_value_error() -> None:
    mapped = to_api_error(ValueError("invalid"), provider="spotify")
    assert mapped.error.code == "VALIDATION_ERROR"
    assert mapped.error.details == {"provider": "spotify"}
