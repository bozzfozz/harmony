from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from fastapi import status
import httpx
import pytest

from app.errors import DependencyError, RateLimitedError
from app.services.secret_store import SecretStore
from app.services.secret_validation import (
    SecretValidationResult,
    SecretValidationService,
    SecretValidationSettings,
)


def _make_response(status_code: int, *, method: str = "GET") -> httpx.Response:
    request = httpx.Request(method, "https://example.test")
    return httpx.Response(status_code=status_code, request=request)


class _StubAsyncClient:
    def __init__(
        self,
        *,
        get_queue: deque[httpx.Response | Exception],
        post_queue: deque[httpx.Response | Exception],
        calls: list[Any],
    ) -> None:
        self._get_queue = get_queue
        self._post_queue = post_queue
        self._calls = calls

    async def __aenter__(self) -> _StubAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        self._calls.append(("GET", url, headers))
        if not self._get_queue:
            raise AssertionError("unexpected GET request")
        item = self._get_queue.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    async def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        self._calls.append(("POST", url, data, headers, auth))
        if not self._post_queue:
            raise AssertionError("unexpected POST request")
        item = self._post_queue.popleft()
        if isinstance(item, Exception):
            raise item
        return item


class _StubClientFactory:
    def __init__(
        self,
        *,
        get: Iterable[httpx.Response | Exception] | None = None,
        post: Iterable[httpx.Response | Exception] | None = None,
    ) -> None:
        self._get = deque(get or [])
        self._post = deque(post or [])
        self.calls: list[Any] = []

    def __call__(self) -> _StubAsyncClient:
        return _StubAsyncClient(get_queue=self._get, post_queue=self._post, calls=self.calls)


def _default_settings() -> SecretValidationSettings:
    return SecretValidationSettings(
        timeout_ms=500, max_requests_per_minute=5, slskd_base_url="http://slskd.local"
    )


def _slskd_store(api_key: str) -> SecretStore:
    return SecretStore.from_values(
        {
            "SLSKD_API_KEY": api_key,
            "SLSKD_URL": "http://slskd.local/api",
        }
    )


def _spotify_store(client_secret: str, *, client_id: str = "client123") -> SecretStore:
    return SecretStore.from_values(
        {
            "SPOTIFY_CLIENT_SECRET": client_secret,
            "SPOTIFY_CLIENT_ID": client_id,
        }
    )


@pytest.mark.asyncio
async def test_validate_slskd_success_returns_live_result() -> None:
    factory = _StubClientFactory(get=[_make_response(status.HTTP_200_OK)])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _slskd_store("ValidKey1234")

    result = await service.validate("slskd_api_key", store=store)

    assert isinstance(result, SecretValidationResult)
    assert result.provider == "slskd_api_key"
    assert result.validated.mode == "live"
    assert result.validated.valid is True
    assert result.validated.reason is None
    assert result.validated.note is None
    method, url, headers = factory.calls[0]
    assert method == "GET"
    assert headers == {"X-API-Key": "ValidKey1234"}
    assert url.endswith("/api/v2/me")


@pytest.mark.asyncio
async def test_validate_slskd_invalid_format_short_circuits() -> None:
    service = SecretValidationService(
        settings=_default_settings(), client_factory=_StubClientFactory()
    )
    store = _slskd_store("invalid key!!!")

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is False
    assert result.validated.reason == "unexpected characters"


@pytest.mark.asyncio
async def test_validate_slskd_invalid_credentials_returns_live_failure() -> None:
    factory = _StubClientFactory(get=[_make_response(status.HTTP_403_FORBIDDEN)])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _slskd_store("ValidKey1234")

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "live"
    assert result.validated.valid is False
    assert result.validated.reason == "invalid credentials"


@pytest.mark.asyncio
async def test_validate_slskd_rate_limit_response_raises_dependency_error() -> None:
    factory = _StubClientFactory(get=[_make_response(status.HTTP_429_TOO_MANY_REQUESTS)])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _slskd_store("ValidKey1234")

    with pytest.raises(DependencyError) as excinfo:
        await service.validate("slskd_api_key", store=store)

    exc = excinfo.value
    assert exc.http_status == status.HTTP_424_FAILED_DEPENDENCY
    assert exc.meta == {"status": status.HTTP_429_TOO_MANY_REQUESTS}


@pytest.mark.asyncio
async def test_validate_slskd_server_error_raises_dependency_error() -> None:
    factory = _StubClientFactory(get=[_make_response(status.HTTP_503_SERVICE_UNAVAILABLE)])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _slskd_store("ValidKey1234")

    with pytest.raises(DependencyError) as excinfo:
        await service.validate("slskd_api_key", store=store)

    exc = excinfo.value
    assert exc.http_status == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc.meta == {"status": status.HTTP_503_SERVICE_UNAVAILABLE}


@pytest.mark.asyncio
async def test_validate_slskd_timeout_falls_back_to_format_result() -> None:
    timeout = httpx.TimeoutException(
        "timeout", request=httpx.Request("GET", "https://example.test")
    )
    factory = _StubClientFactory(get=[timeout])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _slskd_store("ValidKey1234")

    result = await service.validate("slskd_api_key", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is True
    assert result.validated.note == "upstream unreachable"
    assert result.validated.reason is None


@pytest.mark.asyncio
async def test_validate_spotify_success_returns_live_result() -> None:
    factory = _StubClientFactory(post=[_make_response(status.HTTP_200_OK, method="POST")])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _spotify_store("SecretAA")

    result = await service.validate("spotify_client_secret", store=store)

    assert result.provider == "spotify_client_secret"
    assert result.validated.mode == "live"
    assert result.validated.valid is True
    assert result.validated.reason is None
    assert result.validated.note is None
    method, url, data, headers, auth = factory.calls[0]
    assert method == "POST"
    assert url == "https://accounts.spotify.com/api/token"
    assert data == {"grant_type": "client_credentials"}
    assert headers == {"Content-Type": "application/x-www-form-urlencoded"}
    assert auth == ("client123", "SecretAA")


@pytest.mark.asyncio
async def test_validate_spotify_invalid_format_short_circuits() -> None:
    service = SecretValidationService(
        settings=_default_settings(), client_factory=_StubClientFactory()
    )
    store = _spotify_store("invalid secret")

    result = await service.validate("spotify_client_secret", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is False
    assert result.validated.reason == "must consist of alphanumeric characters"


@pytest.mark.asyncio
async def test_validate_spotify_invalid_credentials_returns_live_failure() -> None:
    factory = _StubClientFactory(post=[_make_response(status.HTTP_401_UNAUTHORIZED, method="POST")])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _spotify_store("SecretAA")

    result = await service.validate("spotify_client_secret", store=store)

    assert result.validated.mode == "live"
    assert result.validated.valid is False
    assert result.validated.reason == "invalid credentials"


@pytest.mark.asyncio
async def test_validate_spotify_rate_limit_response_raises_dependency_error() -> None:
    factory = _StubClientFactory(
        post=[_make_response(status.HTTP_429_TOO_MANY_REQUESTS, method="POST")]
    )
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _spotify_store("SecretAA")

    with pytest.raises(DependencyError) as excinfo:
        await service.validate("spotify_client_secret", store=store)

    exc = excinfo.value
    assert exc.http_status == status.HTTP_424_FAILED_DEPENDENCY
    assert exc.meta == {"status": status.HTTP_429_TOO_MANY_REQUESTS}


@pytest.mark.asyncio
async def test_validate_spotify_server_error_raises_dependency_error() -> None:
    factory = _StubClientFactory(
        post=[_make_response(status.HTTP_500_INTERNAL_SERVER_ERROR, method="POST")]
    )
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _spotify_store("SecretAA")

    with pytest.raises(DependencyError) as excinfo:
        await service.validate("spotify_client_secret", store=store)

    exc = excinfo.value
    assert exc.http_status == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc.meta == {"status": status.HTTP_500_INTERNAL_SERVER_ERROR}


@pytest.mark.asyncio
async def test_validate_spotify_timeout_falls_back_to_format_result() -> None:
    timeout = httpx.TimeoutException(
        "timeout", request=httpx.Request("POST", "https://example.test")
    )
    factory = _StubClientFactory(post=[timeout])
    service = SecretValidationService(settings=_default_settings(), client_factory=factory)
    store = _spotify_store("SecretAA")

    result = await service.validate("spotify_client_secret", store=store)

    assert result.validated.mode == "format"
    assert result.validated.valid is True
    assert result.validated.note == "upstream unreachable"
    assert result.validated.reason is None


class _MonotonicStub:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)
        self._last = 0.0

    def __call__(self) -> float:
        try:
            self._last = next(self._values)
        except StopIteration:
            pass
        return self._last


@pytest.mark.asyncio
async def test_enforce_rate_limit_raises_after_threshold() -> None:
    factory = _StubClientFactory(
        get=[_make_response(status.HTTP_200_OK), _make_response(status.HTTP_200_OK)]
    )
    monotonic = _MonotonicStub([0.0, 0.1, 0.2, 1.0, 1.1, 1.2, 2.0])
    settings = SecretValidationSettings(
        timeout_ms=500, max_requests_per_minute=2, slskd_base_url="http://slskd.local"
    )
    service = SecretValidationService(
        settings=settings, client_factory=factory, monotonic=monotonic
    )
    store = _slskd_store("ValidKey1234")

    await service.validate("slskd_api_key", store=store)
    await service.validate("slskd_api_key", store=store)

    with pytest.raises(RateLimitedError) as excinfo:
        await service.validate("slskd_api_key", store=store)

    exc = excinfo.value
    assert exc.http_status == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc.meta is not None
    assert exc.meta["retry_after_ms"] > 0
