"""Tests for the integration error mapping helpers."""

from __future__ import annotations

import pytest

from app.errors import (
    DependencyError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.integrations.errors import to_application_error
from app.integrations.provider_gateway import (
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayInternalError,
    ProviderGatewayNotFoundError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
    ProviderGatewayValidationError,
)


@pytest.mark.parametrize(
    "gateway_error, expected_type, expected_message, expected_meta, expected_headers",
    [
        (
            ProviderGatewayValidationError("spotify", status_code=400, cause=None),
            ValidationAppError,
            "Spotify rejected the search request.",
            {"provider_status": 400},
            None,
        ),
        (
            ProviderGatewayRateLimitedError(
                "spotify",
                retry_after_ms=2000,
                retry_after_header="120",
                cause=None,
                status_code=429,
            ),
            RateLimitedError,
            "Spotify rate limited the search request.",
            {"retry_after_ms": 2000},
            {"Retry-After": "120"},
        ),
        (
            ProviderGatewayNotFoundError("spotify", status_code=404, cause=None),
            NotFoundError,
            "Spotify returned no matching results.",
            None,
            None,
        ),
        (
            ProviderGatewayTimeoutError("spotify", timeout_ms=1500, cause=None),
            DependencyError,
            "Spotify search timed out.",
            {"timeout_ms": 1500},
            None,
        ),
        (
            ProviderGatewayDependencyError("spotify", status_code=503, cause=None),
            DependencyError,
            "Spotify search is currently unavailable.",
            {"provider_status": 503},
            None,
        ),
        (
            ProviderGatewayInternalError("spotify", "failed"),
            InternalServerError,
            "Failed to process Spotify search results.",
            None,
            None,
        ),
    ],
)
def test_error_mapping(
    gateway_error, expected_type, expected_message, expected_meta, expected_headers
):
    app_error = to_application_error("Spotify", gateway_error)

    assert isinstance(app_error, expected_type)
    assert app_error.message == expected_message
    if expected_meta is None:
        assert app_error.meta is None
    else:
        assert app_error.meta == expected_meta
    if expected_headers is None:
        assert app_error.headers is None
    else:
        assert app_error.headers == expected_headers


def test_unknown_error_defaults_to_internal_error():
    error = ProviderGatewayError("spotify", "unexpected")

    app_error = to_application_error("Spotify", error)

    assert isinstance(app_error, InternalServerError)
    assert app_error.message == "Unexpected error during Spotify search."
