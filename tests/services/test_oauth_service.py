from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import parse_qs

import httpx
import pytest
from starlette.requests import Request

from app.config import load_config
from app.services.oauth_service import (
    ManualRateLimiter,
    OAuthErrorCode,
    OAuthManualRequest,
    OAuthManualResponse,
    OAuthService,
)
from app.services.oauth_transactions import OAuthTransactionStore, TransactionNotFoundError


class DummyCacheHandler:
    def __init__(self) -> None:
        self.saved: Mapping[str, Any] | None = None

    def save_token_to_cache(self, token_info: Mapping[str, Any]) -> None:  # type: ignore[override]
        self.saved = dict(token_info)

    def get_cached_token(self) -> Mapping[str, Any] | None:  # type: ignore[override]
        return self.saved


def _build_request(client_ip: str = "203.0.113.10") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/oauth/start",
        "headers": [],
        "client": (client_ip, 54321),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_oauth_service_start_and_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "SPOTIFY_SCOPE": "user-read-email",
        "OAUTH_SESSION_TTL_MIN": "5",
    }
    config = load_config(runtime_env=runtime_env)
    store = OAuthTransactionStore(ttl=timedelta(minutes=config.oauth.session_ttl_minutes))
    cache = DummyCacheHandler()

    def client_factory() -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            params = parse_qs(body)
            assert "code_verifier" in params
            return httpx.Response(
                200,
                json={
                    "access_token": "token123",
                    "token_type": "Bearer",
                    "refresh_token": "refresh123",
                    "expires_in": 3600,
                },
            )

        transport = httpx.MockTransport(handler)
        return httpx.AsyncClient(transport=transport)

    service = OAuthService(
        config=config,
        transactions=store,
        manual_limit=ManualRateLimiter(limit=10, window_seconds=60.0),
        http_client_factory=client_factory,
    )
    service._cache_handler = cache  # type: ignore[attr-defined]

    start_response = service.start(_build_request())
    assert start_response.state
    assert "code_challenge" in start_response.authorization_url

    await service.complete(state=start_response.state, code="auth-code")
    assert cache.saved is not None
    assert cache.saved["access_token"] == "token123"


@pytest.mark.asyncio
async def test_manual_rejects_unknown_state(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "SPOTIFY_SCOPE": "user-read-email",
    }
    config = load_config(runtime_env=runtime_env)
    store = OAuthTransactionStore(ttl=timedelta(minutes=1))
    service = OAuthService(config=config, transactions=store)

    result = await service.manual(
        request=OAuthManualRequest(redirect_url="http://127.0.0.1:8888/callback?code=abc&state=missing"),
        client_ip="198.51.100.10",
    )
    assert not result.ok
    assert result.error_code is OAuthErrorCode.OAUTH_STATE_MISMATCH


@pytest.mark.asyncio
async def test_manual_success_parses_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "SPOTIFY_SCOPE": "user-read-email",
        "OAUTH_SESSION_TTL_MIN": "2",
    }
    config = load_config(runtime_env=runtime_env)
    store = OAuthTransactionStore(ttl=timedelta(minutes=config.oauth.session_ttl_minutes))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "abc",
                "token_type": "Bearer",
                "refresh_token": "refresh",
                "expires_in": 3600,
            },
        )

    service = OAuthService(
        config=config,
        transactions=store,
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    # seed transaction
    start = service.start(_build_request())
    redirect_url = f"http://127.0.0.1:8888/callback?code=auth&state={start.state}"
    response = await service.manual(
        request=OAuthManualRequest(redirect_url=redirect_url),
        client_ip="203.0.113.5",
    )
    assert response.ok
    assert response.state == start.state

    with pytest.raises(TransactionNotFoundError):
        await service.complete(state=start.state, code="auth")

