from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest
from fastapi import FastAPI, Request
from tests.simple_client import SimpleTestClient

from app.api.oauth_public import router_oauth_public
from app.dependencies import get_oauth_service, set_oauth_service_instance
from app.oauth.transactions import TransactionNotFoundError
from app.oauth_callback.app import create_callback_app
from app.services.oauth_service import (
    OAuthErrorCode,
    OAuthManualResponse,
    OAuthSessionStatus,
    OAuthStartResponse,
    OAuthStatusResponse,
)


class StubOAuthService:
    def __init__(self) -> None:
        self.start_calls: list[Request] = []
        self.manual_calls: list[tuple[str, str | None]] = []
        self.complete_calls: list[tuple[str, str]] = []
        self._status_records: dict[str, OAuthStatusResponse] = {}
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
        now = datetime.now(timezone.utc)
        state = "state-123"
        self._status_records[state] = OAuthStatusResponse(
            provider="spotify",
            state=state,
            status=OAuthSessionStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            completed_at=None,
            manual_completion_available=True,
            manual_completion_url="/api/v1/oauth/manual",
            redirect_uri="http://127.0.0.1:8888/callback",
            error_code=None,
            message=None,
        )
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
            self._status_records[state] = OAuthStatusResponse(
                provider="spotify",
                state=state,
                status=OAuthSessionStatus.FAILED,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc),
                completed_at=None,
                manual_completion_available=True,
                manual_completion_url="/api/v1/oauth/manual",
                redirect_uri="http://127.0.0.1:8888/callback",
                error_code=OAuthErrorCode.OAUTH_STATE_MISMATCH,
                message="State is unknown or already used.",
            )
            raise TransactionNotFoundError(state)
        if state == "expired":
            self._status_records[state] = OAuthStatusResponse(
                provider="spotify",
                state=state,
                status=OAuthSessionStatus.EXPIRED,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc),
                completed_at=None,
                manual_completion_available=True,
                manual_completion_url="/api/v1/oauth/manual",
                redirect_uri="http://127.0.0.1:8888/callback",
                error_code=OAuthErrorCode.OAUTH_CODE_EXPIRED,
                message="Authorization code expired.",
            )
            raise ValueError(OAuthErrorCode.OAUTH_CODE_EXPIRED.value)
        self.complete_calls.append((state, code))
        completed_at = datetime.now(timezone.utc)
        self._status_records[state] = OAuthStatusResponse(
            provider="spotify",
            state=state,
            status=OAuthSessionStatus.COMPLETED,
            created_at=completed_at,
            expires_at=completed_at + timedelta(minutes=5),
            completed_at=completed_at,
            manual_completion_available=True,
            manual_completion_url="/api/v1/oauth/manual",
            redirect_uri="http://127.0.0.1:8888/callback",
            error_code=None,
            message="Authorization completed successfully.",
        )
        return {"access_token": "abc"}

    def health(self) -> dict[str, Any]:
        return {"provider": "spotify", "active_transactions": 0}

    def help_page_context(self) -> dict[str, Any]:
        return dict(self._help_context)

    def status(self, state: str) -> OAuthStatusResponse:
        record = self._status_records.get(state)
        if record is not None:
            return record
        now = datetime.now(timezone.utc)
        return OAuthStatusResponse(
            provider="spotify",
            state=state,
            status=OAuthSessionStatus.UNKNOWN,
            created_at=now,
            expires_at=now,
            completed_at=None,
            manual_completion_available=True,
            manual_completion_url="/api/v1/oauth/manual",
            redirect_uri="http://127.0.0.1:8888/callback",
            error_code=None,
            message="State not found",
        )


@pytest.fixture
def test_clients() -> Callable[
    [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
]:
    contexts: list[tuple[SimpleTestClient, SimpleTestClient]] = []

    def _factory(
        service: StubOAuthService,
    ) -> tuple[SimpleTestClient, SimpleTestClient]:
        api_app = FastAPI()
        api_app.include_router(router_oauth_public, prefix="/api/v1")
        callback_app = create_callback_app()

        api_app.dependency_overrides[get_oauth_service] = lambda: service
        callback_app.dependency_overrides[get_oauth_service] = lambda: service

        api_context = SimpleTestClient(api_app)
        callback_context = SimpleTestClient(callback_app)
        contexts.append((api_context, callback_context))
        api_client = api_context.__enter__()
        callback_client = callback_context.__enter__()
        return api_client, callback_client

    yield _factory

    while contexts:
        api_context, callback_context = contexts.pop()
        callback_context.__exit__(None, None, None)
        api_context.__exit__(None, None, None)
    set_oauth_service_instance(None)


def test_start_endpoint_returns_payload(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
    service = StubOAuthService()
    api_client, _ = test_clients(service)

    response = api_client.get("/api/v1/oauth/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "state-123"
    assert service.start_calls


def test_manual_endpoint_passes_redirect(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
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
    api_client, _ = test_clients(service)

    response = api_client.post(
        "/api/v1/oauth/manual",
        json={"redirect_url": "http://127.0.0.1:8888/callback?code=abc&state=def"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == OAuthErrorCode.OAUTH_STATE_MISMATCH.value
    assert service.manual_calls[0][0]


def test_manual_rate_limit_maps_to_429(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
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
    api_client, _ = test_clients(service)

    response = api_client.post(
        "/api/v1/oauth/manual",
        json={"redirect_url": "http://127.0.0.1:8888/callback?code=abc&state=def"},
    )
    assert response.status_code == 429


def test_callback_without_code_renders_help(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
    service = StubOAuthService()
    _, callback_client = test_clients(service)

    response = callback_client.get("/callback")
    assert response.status_code == 200
    assert "192.0.2.10" in response.text


def test_callback_success_calls_service(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
    service = StubOAuthService()
    _, callback_client = test_clients(service)

    response = callback_client.get(
        "/callback",
        params={"code": "auth", "state": "ok"},
    )
    assert response.status_code == 200
    assert service.complete_calls == [("ok", "auth")]


def test_callback_handles_expired_state(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
    service = StubOAuthService()
    _, callback_client = test_clients(service)

    response = callback_client.get(
        "/callback",
        params={"code": "auth", "state": "expired"},
    )
    assert response.status_code == 400
    assert "abgelaufen" in response.text


def test_status_endpoint_returns_payload(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
    service = StubOAuthService()
    api_client, _ = test_clients(service)

    start_response = api_client.get("/api/v1/oauth/start")
    state = start_response.json()["state"]

    response = api_client.get(f"/api/v1/oauth/status/{state}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == OAuthSessionStatus.PENDING.value
    assert payload["manual_completion_url"] == "/api/v1/oauth/manual"
    assert payload["manual_completion_available"] is True


def test_status_endpoint_unknown_state(
    test_clients: Callable[
        [StubOAuthService], tuple[SimpleTestClient, SimpleTestClient]
    ],
) -> None:
    service = StubOAuthService()
    api_client, _ = test_clients(service)

    response = api_client.get("/api/v1/oauth/status/does-not-exist")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == OAuthSessionStatus.UNKNOWN.value


def test_oauth_routes_registered_without_duplicate_prefix() -> None:
    app = FastAPI()
    app.include_router(router_oauth_public, prefix="/api/v1")

    paths = {route.path for route in app.routes if getattr(route, "methods", None)}
    assert "/api/v1/oauth/start" in paths
    assert "/api/v1/oauth/manual" in paths
    assert "/api/v1/oauth/status/{state}" in paths
    assert not any(
        path.lstrip("/").split("/")[:2] == ["api", "v1"]
        and path.lstrip("/").split("/").count("oauth") > 1
        for path in paths
    )


def test_openapi_schema_excludes_callback_route() -> None:
    app = FastAPI()
    app.include_router(router_oauth_public, prefix="/api/v1")

    context = SimpleTestClient(app)
    client = context.__enter__()
    try:
        schema = client.get("/openapi.json").json()
    finally:
        context.__exit__(None, None, None)
    paths = schema["paths"].keys()
    assert "/callback" not in paths
    assert "/api/v1/oauth/start" in paths
