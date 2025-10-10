from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from fastapi import FastAPI, Request

from app.api import oauth as oauth_module
from app.services.oauth_service import (
    OAuthErrorCode,
    OAuthManualResponse,
    OAuthStartResponse,
)
from app.services.oauth_transactions import TransactionNotFoundError
from tests.simple_client import SimpleTestClient


class StubOAuthService:
    def __init__(self) -> None:
        self.start_calls: list[Request] = []
        self.manual_calls: list[tuple[str, str | None]] = []
        self.complete_calls: list[tuple[str, str]] = []
        self._manual_response = OAuthManualResponse(
            ok=True,
            provider="spotify",
            state="state-1",
            completed_at=None,
            message="done",
            error_code=None,
        )
        self._help_context = {
            "redirect_uri": "http://127.0.0.1:8888/callback",
            "public_host_hint": "192.0.2.10",
            "manual_url": "/api/v1/oauth/manual",
        }

    def set_manual_response(self, response: OAuthManualResponse) -> None:
        self._manual_response = response

    def start(self, request: Request) -> OAuthStartResponse:
        self.start_calls.append(request)
        return OAuthStartResponse(
            provider="spotify",
            authorization_url="https://accounts.spotify.com/authorize?state=test",
            state="state-123",
            code_challenge_method="S256",
            expires_at=datetime.now(timezone.utc),
            redirect_uri="http://127.0.0.1:8888/callback",
            manual_completion_available=True,
            manual_completion_url="/api/v1/oauth/manual",
        )

    async def manual(
        self, *, request: Any, client_ip: str | None
    ) -> OAuthManualResponse:
        self.manual_calls.append((getattr(request, "redirect_url", ""), client_ip))
        return self._manual_response

    async def complete(self, *, state: str, code: str) -> dict[str, Any]:
        if state == "missing":
            raise TransactionNotFoundError(state)
        if state == "expired":
            raise ValueError(OAuthErrorCode.OAUTH_CODE_EXPIRED.value)
        self.complete_calls.append((state, code))
        return {"access_token": "abc"}

    def health(self) -> dict[str, Any]:
        return {"provider": "spotify", "active_transactions": 0}

    def help_page_context(self) -> dict[str, Any]:
        return dict(self._help_context)


@pytest.fixture
def test_client() -> Callable[[StubOAuthService], SimpleTestClient]:
    instances: list[SimpleTestClient] = []

    def _factory(service: StubOAuthService) -> SimpleTestClient:
        app = FastAPI()
        app.include_router(oauth_module.router, prefix="/api/v1")
        app.include_router(oauth_module.callback_router)

        app.dependency_overrides[oauth_module.get_oauth_service] = lambda: service  # type: ignore[attr-defined]

        context = SimpleTestClient(app)
        instance = context.__enter__()
        instances.append(context)
        return instance

    yield _factory

    while instances:
        ctx = instances.pop()
        ctx.__exit__(None, None, None)


def test_start_endpoint_returns_payload(test_client: Callable[[StubOAuthService], SimpleTestClient]) -> None:
    service = StubOAuthService()
    client = test_client(service)

    response = client.get("/api/v1/oauth/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "state-123"
    assert service.start_calls


def test_manual_endpoint_passes_redirect(test_client: Callable[[StubOAuthService], SimpleTestClient]) -> None:
    service = StubOAuthService()
    manual_response = OAuthManualResponse(
        ok=False,
        provider="spotify",
        state="state-1",
        completed_at=None,
        error_code=OAuthErrorCode.OAUTH_STATE_MISMATCH,
        message="bad state",
    )
    service.set_manual_response(manual_response)
    client = test_client(service)

    response = client.post(
        "/api/v1/oauth/manual",
        json={"redirect_url": "http://127.0.0.1:8888/callback?code=abc&state=def"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == OAuthErrorCode.OAUTH_STATE_MISMATCH.value
    assert service.manual_calls[0][0]


def test_manual_rate_limit_maps_to_429(test_client: Callable[[StubOAuthService], SimpleTestClient]) -> None:
    service = StubOAuthService()
    rate_limited = OAuthManualResponse(
        ok=False,
        provider="spotify",
        state=None,
        completed_at=None,
        error_code=OAuthErrorCode.OAUTH_MANUAL_RATE_LIMITED,
        message="slow down",
    )
    service.set_manual_response(rate_limited)
    client = test_client(service)

    response = client.post(
        "/api/v1/oauth/manual",
        json={"redirect_url": "http://127.0.0.1:8888/callback?code=abc&state=def"},
    )
    assert response.status_code == 429


def test_callback_without_code_renders_help(test_client: Callable[[StubOAuthService], SimpleTestClient]) -> None:
    service = StubOAuthService()
    client = test_client(service)

    response = client.get("/callback")
    assert response.status_code == 200
    assert "192.0.2.10" in response.text


def test_callback_success_calls_service(test_client: Callable[[StubOAuthService], SimpleTestClient]) -> None:
    service = StubOAuthService()
    client = test_client(service)

    response = client.get(
        "/callback",
        params={"code": "auth", "state": "ok"},
    )
    assert response.status_code == 200
    assert service.complete_calls == [("ok", "auth")]


def test_callback_handles_expired_state(test_client: Callable[[StubOAuthService], SimpleTestClient]) -> None:
    service = StubOAuthService()
    client = test_client(service)

    response = client.get(
        "/callback",
        params={"code": "auth", "state": "expired"},
    )
    assert response.status_code == 400
    assert "abgelaufen" in response.text


