from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import Request

from app.config import load_config
from app.oauth.store_fs import FsOAuthTransactionStore
from app.oauth.transactions import TransactionUsedError
from app.services.oauth_service import (
    ManualRateLimiter,
    OAuthErrorCode,
    OAuthManualRequest,
    OAuthService,
    OAuthSessionStatus,
)


class DummyCache:
    def __init__(self) -> None:
        self.saved: dict[str, Any] | None = None

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:  # type: ignore[override]
        self.saved = dict(token_info)

    def get_cached_token(self) -> dict[str, Any] | None:  # type: ignore[override]
        return self.saved


def _build_request(ip: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/oauth/start",
        "headers": [],
        "client": (ip, 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_oauth_flow_split_mode(tmp_path: Path) -> None:
    runtime_env = {
        "SPOTIFY_CLIENT_ID": "client-id",
        "SPOTIFY_CLIENT_SECRET": "client-secret",
        "SPOTIFY_SCOPE": "user-read-email",
        "OAUTH_SPLIT_MODE": "true",
        "OAUTH_STATE_DIR": str(tmp_path),
        "OAUTH_STORE_HASH_CV": "false",
        "OAUTH_STATE_TTL_SEC": "120",
    }
    config = load_config(runtime_env=runtime_env)

    clock = [datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)]

    def now() -> datetime:
        return clock[0]

    store = FsOAuthTransactionStore(
        tmp_path,
        ttl=timedelta(seconds=config.oauth.state_ttl_seconds),
        hash_code_verifier=False,
        now_fn=now,
    )
    cache = DummyCache()

    def client_factory() -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            params = parse_qs(body)
            assert "code_verifier" in params
            return httpx.Response(
                200,
                json={
                    "access_token": "token123",
                    "refresh_token": "refresh123",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    service = OAuthService(
        config=config,
        transactions=store,
        manual_limit=ManualRateLimiter(limit=10, window_seconds=60.0),
        http_client_factory=client_factory,
    )
    service._cache_handler = cache  # type: ignore[attr-defined]

    start_response = service.start(_build_request())
    assert start_response.state

    await service.complete(state=start_response.state, code="auth-code")
    assert cache.saved is not None
    assert cache.saved["access_token"] == "token123"
    status = service.status(start_response.state)
    assert status.status is OAuthSessionStatus.COMPLETED

    with pytest.raises(TransactionUsedError):
        await service.complete(state=start_response.state, code="auth-code")

    second = service.start(_build_request())
    clock[0] = clock[0] + timedelta(seconds=200)
    with pytest.raises(ValueError) as exc:
        await service.complete(state=second.state, code="another")
    assert exc.value.args[0] == OAuthErrorCode.OAUTH_CODE_EXPIRED.value

    manual_response = await service.manual(
        request=OAuthManualRequest(
            redirect_url=f"http://127.0.0.1:8888/callback?code=abc&state={second.state}"
        ),
        client_ip="198.51.100.5",
    )
    assert not manual_response.ok
    assert manual_response.error_code is OAuthErrorCode.OAUTH_CODE_EXPIRED
