import contextlib
import os

import httpx
import pytest

from app.integrations.slskd_client import SlskdDownloadStatus, SlskdHttpClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture(autouse=True)
def _stub_session_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.contextmanager
    def _fake_scope():
        class _Query:
            def delete(self) -> None:  # pragma: no cover - helper
                return None

        class _Session:
            def query(self, *_: object, **__: object) -> _Query:
                return _Query()

        yield _Session()

    monkeypatch.setattr("app.db.session_scope", _fake_scope)
    monkeypatch.setattr("tests.conftest.session_scope", _fake_scope)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.mark.asyncio
async def test_enqueue_download_attaches_headers() -> None:
    captured: dict[str, str] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json={"status": "accepted"})

    transport = httpx.MockTransport(_handler)
    client = SlskdHttpClient(
        base_url="http://slskd",
        api_key="secret",
        transport=transport,
        max_attempts=1,
    )

    await client.enqueue_download(
        "collector", [{"filename": "song.flac"}], idempotency_key="job-123"
    )

    assert captured["Idempotency-Key"] == "job-123"
    assert captured["X-API-Key"] == "secret"


@pytest.mark.asyncio
async def test_request_uses_retry_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int, int]] = []

    async def _fake_with_retry(
        async_fn, *, attempts, base_ms, jitter_pct, timeout_ms, classify_err
    ):
        calls.append((attempts, base_ms, jitter_pct, timeout_ms))
        return httpx.Response(200, json={"status": "completed"})

    monkeypatch.setattr("app.integrations.slskd_client.with_retry", _fake_with_retry)

    client = SlskdHttpClient(
        base_url="http://slskd",
        api_key=None,
        max_attempts=5,
        backoff_base_ms=500,
        jitter_pct=15,
    )

    response = await client.search_tracks("Song", limit=1, timeout_ms=4000)
    assert response["status"] == "completed"

    assert calls == [(5, 500, 15, 4000)]


@pytest.mark.asyncio
async def test_stream_download_events_classifies_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        {"status": "accepted", "download_id": "dl-1"},
        {"status": "downloading", "bytes_written": 1024},
        {"status": "Completed", "path": "/downloads/song.flac", "bytes_written": 2048},
    ]

    counter = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal counter
        index = min(counter, len(responses) - 1)
        counter += 1
        return httpx.Response(200, json=responses[index])

    transport = httpx.MockTransport(_handler)
    client = SlskdHttpClient(
        base_url="http://slskd",
        transport=transport,
        max_attempts=1,
        status_poll_interval=0.01,
    )

    events: list[tuple[SlskdDownloadStatus, str | None]] = []

    async for event in client.stream_download_events("job-1", poll_interval=0.01):
        events.append((event.status, event.path))

    assert events[0][0] is SlskdDownloadStatus.ACCEPTED
    assert events[1][0] is SlskdDownloadStatus.IN_PROGRESS
    assert events[2][0] is SlskdDownloadStatus.COMPLETED
    assert events[2][1] == "/downloads/song.flac"
