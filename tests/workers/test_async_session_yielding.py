"""Ensure worker coroutines remain responsive when database access is slow."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Mapping

import pytest

from app.orchestrator.handlers import MatchingHandlerDeps, handle_matching
from app.workers.lyrics_worker import LyricsWorker
from app.workers.sync_worker import SyncWorker


class _FakeSession:
    """Minimal session stub for worker tests."""

    def __init__(self, download: SimpleNamespace | None = None) -> None:
        self.download = download
        self.matches: list[Any] = []

    def get(self, _model: Any, _identifier: Any) -> SimpleNamespace | None:
        return self.download

    def add(self, instance: Any) -> None:  # pragma: no cover - exercised in assertions
        if isinstance(instance, SimpleNamespace):
            self.matches.append(instance)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __enter__(self) -> _FakeSession:
        return self._session

    def __exit__(self, *_exc: object) -> None:
        return None


async def _wait_for_event(event: asyncio.Event, *, timeout: float = 0.2) -> None:
    await asyncio.wait_for(event.wait(), timeout=timeout)


def _install_slow_run_session(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    *,
    delay: float,
    session_factory: Callable[[], _FakeSessionContext] | None = None,
) -> tuple[asyncio.Event, _FakeSession]:
    started = asyncio.Event()
    session = session_factory()._session if session_factory else _FakeSession()

    async def slow_run_session(func: Callable[[Any], Any], *, factory=None):  # type: ignore[override]
        started.set()

        def runner() -> Any:
            time.sleep(delay)
            context_factory = factory or session_factory
            if context_factory is not None:
                with context_factory() as scoped:
                    return func(scoped)
            return func(session)

        return await asyncio.to_thread(runner)

    monkeypatch.setattr(target, slow_run_session)
    return started, session


@pytest.mark.asyncio
async def test_sync_worker_enqueue_yields_with_slow_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.workers.sync_worker.read_setting", lambda _key: None)

    worker = SyncWorker(SimpleNamespace())
    worker._running.set()

    download = SimpleNamespace(
        job_id=None,
        username=None,
        request_payload={},
        priority=0,
        state="queued",
        next_retry_at=None,
        updated_at=None,
    )
    session = _FakeSession(download)

    started, _ = _install_slow_run_session(
        monkeypatch,
        "app.workers.sync_worker.run_session",
        delay=0.05,
        session_factory=lambda: _FakeSessionContext(session),
    )

    monkeypatch.setattr(
        "app.workers.sync_worker.enqueue",
        lambda *_args, **_kwargs: SimpleNamespace(id=1, priority=0),
    )

    async def fake_put_job(self: SyncWorker, _job: Any) -> None:
        return None

    monkeypatch.setattr(SyncWorker, "_put_job", fake_put_job)

    resume = asyncio.Event()

    async def monitor() -> None:
        await started.wait()
        await asyncio.sleep(0.01)
        resume.set()

    monitor_task = asyncio.create_task(monitor())
    worker_task = asyncio.create_task(
        worker.enqueue({"files": [{"download_id": 1, "priority": 1}], "username": "alice"})
    )

    await _wait_for_event(resume)
    await worker_task
    await monitor_task


@pytest.mark.asyncio
async def test_sync_worker_refresh_downloads_yields_with_slow_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.workers.sync_worker.read_setting", lambda _key: None)
    monkeypatch.setattr("app.workers.sync_worker.write_setting", lambda *args, **kwargs: None)
    monkeypatch.setattr(SyncWorker, "_record_heartbeat", lambda self: None)

    class _Client:
        async def get_download_status(self) -> Iterable[Mapping[str, Any]]:
            return [{"download_id": 5, "state": "downloading", "progress": 25}]

        async def cancel_download(self, _identifier: str) -> None:
            return None

    worker = SyncWorker(_Client())

    download = SimpleNamespace(
        state="queued",
        progress=0.0,
        request_payload={},
        priority=0,
        username="alice",
        next_retry_at=None,
        updated_at=None,
    )
    session = _FakeSession(download)

    started, _ = _install_slow_run_session(
        monkeypatch,
        "app.workers.sync_worker.run_session",
        delay=0.05,
        session_factory=lambda: _FakeSessionContext(session),
    )

    async def fake_handle_completion(self: SyncWorker, *_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(SyncWorker, "_handle_download_completion", fake_handle_completion)

    resume = asyncio.Event()

    async def monitor() -> None:
        await started.wait()
        await asyncio.sleep(0.01)
        resume.set()

    monitor_task = asyncio.create_task(monitor())
    worker_task = asyncio.create_task(worker.refresh_downloads())

    await _wait_for_event(resume)
    await worker_task
    await monitor_task


@pytest.mark.asyncio
async def test_lyrics_worker_update_download_yields_with_slow_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = LyricsWorker()

    download = SimpleNamespace(
        lyrics_status="pending",
        lyrics_path=None,
        has_lyrics=False,
        updated_at=None,
    )
    session = _FakeSession(download)

    started, _ = _install_slow_run_session(
        monkeypatch,
        "app.workers.lyrics_worker.run_session",
        delay=0.05,
        session_factory=lambda: _FakeSessionContext(session),
    )

    resume = asyncio.Event()

    async def monitor() -> None:
        await started.wait()
        await asyncio.sleep(0.01)
        resume.set()

    monitor_task = asyncio.create_task(monitor())
    worker_task = asyncio.create_task(
        worker._update_download(7, status="done", path="/tmp/song.lrc")
    )

    await _wait_for_event(resume)
    await worker_task
    await monitor_task


@pytest.mark.asyncio
async def test_handle_matching_yields_with_slow_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.settings_store.increment_counter", lambda *args, **kwargs: 0)
    monkeypatch.setattr("app.utils.settings_store.write_setting", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.orchestrator.handlers.record_activity", lambda *args, **kwargs: None)

    class _Engine:
        def calculate_slskd_match_confidence(self, *_args: Any, **_kwargs: Any) -> float:
            return 0.9

    session = _FakeSession()
    session_factory = lambda: _FakeSessionContext(session)

    started, _ = _install_slow_run_session(
        monkeypatch,
        "app.orchestrator.handlers.run_session",
        delay=0.05,
        session_factory=session_factory,
    )

    monkeypatch.setattr(
        "app.orchestrator.handlers.Match",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    deps = MatchingHandlerDeps(
        engine=_Engine(),
        session_factory=session_factory,
        confidence_threshold=0.1,
        external_timeout_ms=1000,
    )

    job = SimpleNamespace(
        id=1,
        type="matching",
        payload={
            "spotify_track": {"id": "track-1"},
            "candidates": [{"id": "cand-1"}],
        },
    )

    resume = asyncio.Event()

    async def monitor() -> None:
        await started.wait()
        await asyncio.sleep(0.01)
        resume.set()

    monitor_task = asyncio.create_task(monitor())
    handler_task = asyncio.create_task(handle_matching(job, deps))

    await _wait_for_event(resume)
    await handler_task
    await monitor_task
