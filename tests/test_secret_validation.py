from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import pytest

from app.errors import DependencyError, RateLimitedError, ValidationAppError
from app.main import app
from app.services.secret_store import SecretStore
from app.services.secret_validation import (SecretValidationDetails,
                                            SecretValidationResult,
                                            SecretValidationService,
                                            SecretValidationSettings)
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient


def _service_with_transport(handler: httpx.MockTransport) -> SecretValidationService:
    settings = SecretValidationSettings(
        timeout_ms=400, max_requests_per_minute=10, slskd_base_url="http://slskd"
    )

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=handler, timeout=0.4)

    return SecretValidationService(settings=settings, client_factory=client_factory)


@pytest.mark.asyncio
async def test_slskd_format_invalid_without_secret() -> None:
    service = SecretValidationService(
        settings=SecretValidationSettings(
            timeout_ms=300, max_requests_per_minute=5, slskd_base_url="http://slskd"
        )
    )
    store = SecretStore.from_values({"SLSKD_API_KEY": ""})

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is False
    assert result.validated.reason == "secret not configured"


@pytest.mark.asyncio
async def test_slskd_live_validates_successfully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "abcdef123456"
        assert request.url.path == "/api/v2/me"
        return httpx.Response(200)

    service = _service_with_transport(httpx.MockTransport(handler))
    store = SecretStore.from_values(
        {"SLSKD_API_KEY": "abcdef123456", "SLSKD_URL": "http://localhost:5030"}
    )

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "live"
    assert result.validated.valid is True


@pytest.mark.asyncio
async def test_slskd_live_with_prefixed_store_url() -> None:
    captured_path: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_path.append(request.url.path)
        return httpx.Response(200)

    service = _service_with_transport(httpx.MockTransport(handler))
    store = SecretStore.from_values(
        {"SLSKD_API_KEY": "abcdef123456", "SLSKD_URL": "http://slskd:5030/api"}
    )

    await service.validate("slskd_api_key", store=store)

    assert captured_path == ["/api/v2/me"]


@pytest.mark.asyncio
async def test_slskd_live_reports_invalid_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    service = _service_with_transport(httpx.MockTransport(handler))
    store = SecretStore.from_values(
        {"SLSKD_API_KEY": "abcdef123456", "SLSKD_URL": "http://localhost:5030"}
    )

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "live"
    assert result.validated.valid is False
    assert result.validated.reason == "invalid credentials"


@pytest.mark.asyncio
async def test_slskd_timeout_falls_back_to_format() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    service = _service_with_transport(httpx.MockTransport(handler))
    store = SecretStore.from_values(
        {"SLSKD_API_KEY": "abcdef123456", "SLSKD_URL": "http://localhost:5030"}
    )

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is True
    assert result.validated.note == "upstream unreachable"


@pytest.mark.asyncio
async def test_slskd_rate_limit_raises() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(200))
    settings = SecretValidationSettings(
        timeout_ms=200, max_requests_per_minute=1, slskd_base_url="http://slskd"
    )
    service = SecretValidationService(
        settings=settings, client_factory=lambda: httpx.AsyncClient(transport=handler, timeout=0.2)
    )
    store = SecretStore.from_values(
        {"SLSKD_API_KEY": "abcdef123456", "SLSKD_URL": "http://localhost:5030"}
    )

    await service.validate("slskd_api_key", store=store)
    with pytest.raises(RateLimitedError):
        await service.validate("slskd_api_key", store=store)


@pytest.mark.asyncio
async def test_slskd_dependency_error_for_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    service = _service_with_transport(httpx.MockTransport(handler))
    store = SecretStore.from_values(
        {"SLSKD_API_KEY": "abcdef123456", "SLSKD_URL": "http://localhost:5030"}
    )

    with pytest.raises(DependencyError):
        await service.validate("slskd_api_key", store=store)


@pytest.mark.asyncio
async def test_spotify_missing_client_id_returns_format_error() -> None:
    service = SecretValidationService(
        settings=SecretValidationSettings(
            timeout_ms=300, max_requests_per_minute=5, slskd_base_url="http://slskd"
        )
    )
    store = SecretStore.from_values({"SPOTIFY_CLIENT_SECRET": "secret", "SPOTIFY_CLIENT_ID": ""})

    result = await service.validate("spotify_client_secret", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is False
    assert result.validated.reason == "spotify client id missing"


@pytest.mark.asyncio
async def test_spotify_live_valid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") is not None
        assert request.url.path == "/api/token"
        return httpx.Response(200)

    service = _service_with_transport(httpx.MockTransport(handler))
    store = SecretStore.from_values(
        {"SPOTIFY_CLIENT_SECRET": "secret", "SPOTIFY_CLIENT_ID": "client"}
    )

    result = await service.validate("spotify_client_secret", store=store)

    assert result.validated.mode == "live"
    assert result.validated.valid is True


@pytest.mark.asyncio
async def test_spotify_invalid_credentials() -> None:
    service = _service_with_transport(httpx.MockTransport(lambda request: httpx.Response(401)))
    store = SecretStore.from_values(
        {"SPOTIFY_CLIENT_SECRET": "secret", "SPOTIFY_CLIENT_ID": "client"}
    )

    result = await service.validate("spotify_client_secret", store=store)

    assert result.validated.mode == "live"
    assert result.validated.valid is False
    assert result.validated.reason == "invalid credentials"


@pytest.mark.asyncio
async def test_spotify_dependency_error_for_429() -> None:
    service = _service_with_transport(httpx.MockTransport(lambda request: httpx.Response(429)))
    store = SecretStore.from_values(
        {"SPOTIFY_CLIENT_SECRET": "secret", "SPOTIFY_CLIENT_ID": "client"}
    )

    with pytest.raises(DependencyError):
        await service.validate("spotify_client_secret", store=store)


@dataclass
class _StubValidationService:
    result: Optional[SecretValidationResult] = None
    error: Optional[Exception] = None

    async def validate(
        self,
        provider: str,
        *,
        store: Any,
        override: Optional[str] = None,
    ) -> SecretValidationResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_validate_secret_endpoint_success() -> None:
    details = SecretValidationDetails(mode="live", valid=True, at=datetime.now(timezone.utc))
    result = SecretValidationResult(provider="slskd_api_key", validated=details)
    stub = _StubValidationService(result=result)

    with SimpleTestClient(app) as client:
        original = getattr(client.app.state, "secret_validation_service", None)
        client.app.state.secret_validation_service = stub
        try:
            response = client.post(api_path("/secrets/slskd_api_key/validate"), json={})
        finally:
            client.app.state.secret_validation_service = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["provider"] == "slskd_api_key"
    assert payload["data"]["validated"]["mode"] == "live"


def test_validate_secret_endpoint_validation_error() -> None:
    stub = _StubValidationService(error=ValidationAppError("Override value must not be empty."))

    with SimpleTestClient(app) as client:
        original = getattr(client.app.state, "secret_validation_service", None)
        client.app.state.secret_validation_service = stub
        try:
            response = client.post(
                api_path("/secrets/slskd_api_key/validate"),
                json={"value": "   "},
            )
        finally:
            client.app.state.secret_validation_service = original

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_validate_secret_endpoint_dependency_error() -> None:
    stub = _StubValidationService(
        error=DependencyError("validation failed: upstream", status_code=503, meta={"status": 503})
    )

    with SimpleTestClient(app) as client:
        original = getattr(client.app.state, "secret_validation_service", None)
        client.app.state.secret_validation_service = stub
        try:
            response = client.post(api_path("/secrets/slskd_api_key/validate"), json={})
        finally:
            client.app.state.secret_validation_service = original

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "DEPENDENCY_ERROR"
