from app.errors import (DependencyError, InternalServerError, NotFoundError,
                        RateLimitedError, ValidationAppError)
from app.integrations.errors import to_application_error
from app.integrations.provider_gateway import (ProviderGatewayDependencyError,
                                               ProviderGatewayInternalError,
                                               ProviderGatewayNotFoundError,
                                               ProviderGatewayRateLimitedError,
                                               ProviderGatewayTimeoutError,
                                               ProviderGatewayValidationError)


def test_validation_error_mapping() -> None:
    error = ProviderGatewayValidationError("stub", status_code=400)
    mapped = to_application_error("spotify", error)
    assert isinstance(mapped, ValidationAppError)
    assert mapped.meta == {"provider_status": 400}


def test_rate_limited_error_mapping() -> None:
    error = ProviderGatewayRateLimitedError(
        "stub",
        retry_after_ms=500,
        retry_after_header="1",
        status_code=429,
    )
    mapped = to_application_error("slskd", error)
    assert isinstance(mapped, RateLimitedError)
    assert mapped.meta == {"retry_after_ms": 500}
    assert mapped.headers == {"Retry-After": "1"}


def test_not_found_error_mapping() -> None:
    error = ProviderGatewayNotFoundError("stub", status_code=404)
    mapped = to_application_error("slskd", error)
    assert isinstance(mapped, NotFoundError)


def test_timeout_error_mapping() -> None:
    error = ProviderGatewayTimeoutError("stub", timeout_ms=1000)
    mapped = to_application_error("spotify", error)
    assert isinstance(mapped, DependencyError)
    assert mapped.meta == {"timeout_ms": 1000}


def test_dependency_error_mapping() -> None:
    error = ProviderGatewayDependencyError("stub", status_code=502)
    mapped = to_application_error("slskd", error)
    assert isinstance(mapped, DependencyError)
    assert mapped.meta == {"provider_status": 502}


def test_internal_error_mapping_default() -> None:
    error = ProviderGatewayInternalError("stub", "boom")
    mapped = to_application_error("spotify", error)
    assert isinstance(mapped, InternalServerError)
