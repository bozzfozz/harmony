"""Focused tests for :mod:`app.services.oauth_service`."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import sys
from threading import Barrier
import time
from typing import Any

import pytest

from app.config import load_config
from app.oauth.store_memory import MemoryOAuthTransactionStore
from app.services.oauth_service import (
    ManualRateLimiter,
    OAuthErrorCode,
    OAuthManualRequest,
    OAuthService,
    OAuthSessionStatus,
)


@dataclass(slots=True)
class FrozenClock:
    """Deterministic clock helper used for transaction expiration tests."""

    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class StubResponse:
    """Minimal httpx-like response."""

    def __init__(self, status_code: int, payload: Mapping[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = dict(payload or {})

    def json(self) -> Mapping[str, Any]:
        return dict(self._payload)


class StubAsyncClient:
    """Async client capturing outgoing requests for assertions."""

    def __init__(self, responses: deque[StubResponse], calls: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._calls = calls

    async def __aenter__(self) -> StubAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def post(
        self, url: str, *, data: Mapping[str, Any], headers: Mapping[str, Any]
    ) -> StubResponse:
        self._calls.append({"url": url, "data": dict(data), "headers": dict(headers)})
        if not self._responses:
            raise AssertionError("Unexpected HTTP call without a stubbed response")
        return self._responses.popleft()


class StubHttpClientFactory:
    """Factory producing :class:`StubAsyncClient` instances."""

    def __init__(self) -> None:
        self.responses: deque[StubResponse] = deque()
        self.calls: list[dict[str, Any]] = []

    def enqueue(self, status_code: int, payload: Mapping[str, Any] | None = None) -> None:
        self.responses.append(StubResponse(status_code, payload))

    def __call__(self) -> StubAsyncClient:
        return StubAsyncClient(self.responses, self.calls)


@pytest.fixture()
def app_config():
    return load_config()


@pytest.fixture()
def frozen_clock() -> FrozenClock:
    return FrozenClock(datetime.now(UTC))


@pytest.fixture()
def store_factory(frozen_clock: FrozenClock) -> Callable[[int], MemoryOAuthTransactionStore]:
    def factory(ttl_seconds: int = 600) -> MemoryOAuthTransactionStore:
        return MemoryOAuthTransactionStore(
            ttl=timedelta(seconds=ttl_seconds), now_fn=frozen_clock.now
        )

    return factory


@pytest.fixture()
def http_client_stub() -> StubHttpClientFactory:
    return StubHttpClientFactory()


def _build_service(
    *,
    config,
    store: MemoryOAuthTransactionStore,
    http_client_factory: StubHttpClientFactory,
    manual_limit: ManualRateLimiter | None = None,
) -> OAuthService:
    return OAuthService(
        config=config,
        transactions=store,
        manual_limit=manual_limit,
        http_client_factory=http_client_factory,
    )


def _build_service_with_public_base(
    public_base: str, *, manual_enabled: bool = True
) -> OAuthService:
    store = MemoryOAuthTransactionStore(ttl=timedelta(seconds=600))
    oauth_config = SimpleNamespace(
        redirect_uri="http://127.0.0.1:8888/callback",
        manual_callback_enabled=manual_enabled,
        public_host_hint=None,
        public_base=public_base,
    )
    spotify_config = SimpleNamespace(client_id="id", client_secret="secret", scope="scope")
    app_config = SimpleNamespace(oauth=oauth_config, spotify=spotify_config)
    return OAuthService(config=app_config, transactions=store)


def _prime_transaction(
    service: OAuthService,
    store: MemoryOAuthTransactionStore,
    *,
    state: str,
    code_verifier: str,
    created_at: datetime,
    redirect_uri: str,
) -> None:
    store.create(
        state=state,
        code_verifier=code_verifier,
        meta={"redirect_uri": redirect_uri, "provider": "spotify"},
        ttl_seconds=int(store.ttl.total_seconds()),
    )
    service._record_pending_status(state=state, created_at=created_at)


def test_manual_rate_limiter_honours_window(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = ManualRateLimiter(limit=2, window_seconds=1.0)
    ticks = iter([0.0, 0.1, 0.2, 1.5, 1.6])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))

    limiter.check("client")
    limiter.check("client")
    with pytest.raises(RuntimeError):
        limiter.check("client")

    limiter.check("client")
    limiter.check("client")


def test_manual_rate_limiter_blocks_concurrent_burst() -> None:
    """Concurrent bursts should not exceed the configured limit."""

    limit = 3
    burst = limit * 10
    limiter = ManualRateLimiter(limit=limit, window_seconds=10.0)

    class SleepingList(list[float]):
        def append(self, item: float) -> None:  # type: ignore[override]
            time.sleep(0.001)
            super().append(item)

    limiter._hits["concurrent-client"] = SleepingList()

    original_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        results = asyncio.run(_run_concurrent_checks(limiter=limiter, burst=burst))
    finally:
        sys.setswitchinterval(original_interval)

    allowed = sum(1 for result in results if result == "allowed")
    failures = [result for result in results if isinstance(result, RuntimeError)]
    assert allowed + len(failures) == burst
    assert allowed == limit
    assert len(failures) == burst - limit
    assert len(limiter._hits.get("concurrent-client", [])) == limit  # noqa: SLF001


async def _run_concurrent_checks(*, limiter: ManualRateLimiter, burst: int) -> list[Any]:
    loop = asyncio.get_running_loop()
    results: list[Any] = []
    with ThreadPoolExecutor(max_workers=burst) as executor:
        barrier = Barrier(burst)

        def worker() -> str:
            barrier.wait(timeout=5)
            limiter.check("concurrent-client")
            return "allowed"

        futures = [loop.run_in_executor(executor, worker) for _ in range(burst)]
        results = await asyncio.gather(*futures, return_exceptions=True)
    return results


def test_update_status_record_tracks_transitions(
    app_config,
    store_factory: Callable[[int], MemoryOAuthTransactionStore],
    http_client_stub: StubHttpClientFactory,
) -> None:
    store = store_factory()
    service = _build_service(config=app_config, store=store, http_client_factory=http_client_stub)
    state = "state-status"
    reference = datetime.now(UTC)

    service._update_status_record(
        state,
        status=OAuthSessionStatus.PENDING,
        message="Waiting for authorization.",
        reference=reference,
    )
    pending = service.status(state)
    assert pending.status is OAuthSessionStatus.PENDING
    assert pending.created_at == reference
    assert pending.expires_at == reference + store.ttl

    service._update_status_record(
        state,
        status=OAuthSessionStatus.FAILED,
        message="State mismatch.",
        error_code=OAuthErrorCode.OAUTH_STATE_MISMATCH,
    )
    failed = service.status(state)
    assert failed.status is OAuthSessionStatus.FAILED
    assert failed.error_code is OAuthErrorCode.OAUTH_STATE_MISMATCH
    assert failed.message == "State mismatch."
    assert failed.manual_completion_available is True


@pytest.mark.asyncio()
async def test_manual_success_updates_status(
    app_config,
    frozen_clock: FrozenClock,
    store_factory: Callable[[int], MemoryOAuthTransactionStore],
    http_client_stub: StubHttpClientFactory,
) -> None:
    store = store_factory()
    http_client_stub.enqueue(200, {"access_token": "token", "expires_in": 3600})
    service = _build_service(config=app_config, store=store, http_client_factory=http_client_stub)
    state = "state-success"
    code = "code-success"

    _prime_transaction(
        service,
        store,
        state=state,
        code_verifier="verifier-success",
        created_at=frozen_clock.now(),
        redirect_uri=app_config.oauth.redirect_uri,
    )

    request = OAuthManualRequest(
        redirect_url=f"{app_config.oauth.redirect_uri}?code={code}&state={state}"
    )
    result = await service.manual(request=request, client_ip="127.0.0.1")

    assert result.ok is True
    assert result.error_code is None
    assert result.state == state
    assert len(http_client_stub.calls) == 1
    assert http_client_stub.calls[0]["data"]["code"] == code

    status = service.status(state)
    assert status.status is OAuthSessionStatus.COMPLETED
    assert status.message == "Authorization completed successfully."
    assert status.completed_at is not None


@pytest.mark.asyncio()
async def test_manual_reports_expired_state(
    app_config,
    frozen_clock: FrozenClock,
    store_factory: Callable[[int], MemoryOAuthTransactionStore],
    http_client_stub: StubHttpClientFactory,
) -> None:
    frozen_clock.advance(-45)
    store = store_factory(ttl_seconds=30)
    service = _build_service(config=app_config, store=store, http_client_factory=http_client_stub)
    state = "state-expired"

    _prime_transaction(
        service,
        store,
        state=state,
        code_verifier="verifier-expired",
        created_at=frozen_clock.now(),
        redirect_uri=app_config.oauth.redirect_uri,
    )

    request = OAuthManualRequest(
        redirect_url=f"{app_config.oauth.redirect_uri}?code=expired&state={state}"
    )
    result = await service.manual(request=request, client_ip="198.51.100.1")

    assert result.ok is False
    assert result.error_code is OAuthErrorCode.OAUTH_CODE_EXPIRED
    assert not http_client_stub.calls

    status = service.status(state)
    assert status.status is OAuthSessionStatus.EXPIRED
    assert status.error_code is OAuthErrorCode.OAUTH_CODE_EXPIRED


@pytest.mark.asyncio()
async def test_manual_rejects_reused_state(
    app_config,
    frozen_clock: FrozenClock,
    store_factory: Callable[[int], MemoryOAuthTransactionStore],
    http_client_stub: StubHttpClientFactory,
) -> None:
    store = store_factory()
    http_client_stub.enqueue(200, {"access_token": "token", "expires_in": 3600})
    service = _build_service(config=app_config, store=store, http_client_factory=http_client_stub)
    state = "state-reuse"

    _prime_transaction(
        service,
        store,
        state=state,
        code_verifier="verifier-reuse",
        created_at=frozen_clock.now(),
        redirect_uri=app_config.oauth.redirect_uri,
    )

    request = OAuthManualRequest(
        redirect_url=f"{app_config.oauth.redirect_uri}?code=reuse&state={state}"
    )
    first = await service.manual(request=request, client_ip="203.0.113.10")
    assert first.ok is True
    assert len(http_client_stub.calls) == 1

    second = await service.manual(request=request, client_ip="203.0.113.10")
    assert second.ok is False
    assert second.error_code is OAuthErrorCode.OAUTH_STATE_MISMATCH
    assert len(http_client_stub.calls) == 1

    status = service.status(state)
    assert status.status is OAuthSessionStatus.FAILED
    assert status.error_code is OAuthErrorCode.OAUTH_STATE_MISMATCH


@pytest.mark.asyncio()
async def test_manual_rate_limited_returns_error(
    app_config,
    frozen_clock: FrozenClock,
    store_factory: Callable[[int], MemoryOAuthTransactionStore],
    http_client_stub: StubHttpClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = store_factory()
    http_client_stub.enqueue(200, {"access_token": "token", "expires_in": 3600})
    limiter = ManualRateLimiter(limit=1, window_seconds=120)
    service = _build_service(
        config=app_config,
        store=store,
        http_client_factory=http_client_stub,
        manual_limit=limiter,
    )
    state = "state-rate"

    _prime_transaction(
        service,
        store,
        state=state,
        code_verifier="verifier-rate",
        created_at=frozen_clock.now(),
        redirect_uri=app_config.oauth.redirect_uri,
    )

    request = OAuthManualRequest(
        redirect_url=f"{app_config.oauth.redirect_uri}?code=rate&state={state}"
    )
    ticks = iter([0.0, 0.0])

    def fake_monotonic() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 9999.0

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    first = await service.manual(request=request, client_ip="192.0.2.10")
    assert first.ok is True

    second = await service.manual(request=request, client_ip="192.0.2.10")
    assert second.ok is False
    assert second.error_code is OAuthErrorCode.OAUTH_MANUAL_RATE_LIMITED
    assert second.state is None
    assert len(http_client_stub.calls) == 1

    status = service.status(state)
    assert status.status is OAuthSessionStatus.COMPLETED


def test_help_page_context_uses_relative_manual_url() -> None:
    service = _build_service_with_public_base("/api/v1/oauth")

    context = service.help_page_context()

    assert context["manual_url"] == "/api/v1/oauth/manual"


def test_help_page_context_supports_absolute_manual_url() -> None:
    base = "https://harmony.example.com/api/v1/oauth"
    service = _build_service_with_public_base(base)

    context = service.help_page_context()

    assert context["manual_url"] == f"{base}/manual"


def test_help_page_context_supports_absolute_root_manual_url() -> None:
    base = "https://harmony.example.com"
    service = _build_service_with_public_base(base)

    context = service.help_page_context()

    assert context["manual_url"] == f"{base}/manual"


def test_help_page_context_omits_manual_url_when_disabled() -> None:
    service = _build_service_with_public_base("/api/v1/oauth", manual_enabled=False)

    context = service.help_page_context()

    assert context["manual_url"] is None
