from __future__ import annotations

import pytest
from tests.support.async_utils import wait_for_event

from app.main import app

pytestmark = [pytest.mark.usefixtures("lifespan_worker_settings")]


def _record_async_call(store: list[str], name: str):
    async def _wrapper(self) -> None:  # type: ignore[override]
        store.append(name)

    return _wrapper


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_lifespan_initialises_orchestrator_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts: list[str] = []
    stops: list[str] = []

    for path, label in (
        ("app.workers.metadata_worker.MetadataWorker.start", "MetadataWorker"),
        ("app.workers.artwork_worker.ArtworkWorker.start", "ArtworkWorker"),
        ("app.workers.lyrics_worker.LyricsWorker.start", "LyricsWorker"),
    ):
        monkeypatch.setattr(path, _record_async_call(starts, label), raising=False)
    for path, label in (
        ("app.workers.metadata_worker.MetadataWorker.stop", "MetadataWorker"),
        ("app.workers.artwork_worker.ArtworkWorker.stop", "ArtworkWorker"),
        ("app.workers.lyrics_worker.LyricsWorker.stop", "LyricsWorker"),
    ):
        monkeypatch.setattr(path, _record_async_call(stops, label), raising=False)

    captured_scheduler = None
    captured_dispatcher = None

    async with app.router.lifespan_context(app):
        runtime = app.state.orchestrator_runtime
        assert runtime is not None, "orchestrator runtime should be initialised"
        captured_scheduler = runtime.scheduler
        captured_dispatcher = runtime.dispatcher
        assert await wait_for_event(captured_scheduler.started, timeout=0.1)
        assert await wait_for_event(captured_dispatcher.started, timeout=0.1)

    assert captured_scheduler is not None
    assert captured_dispatcher is not None
    assert captured_scheduler.stop_requested is True
    assert captured_dispatcher.stop_requested is True
    assert await wait_for_event(captured_scheduler.stopped, timeout=0.1)
    assert await wait_for_event(captured_dispatcher.stopped, timeout=0.1)

    # Metadata worker is always created; artwork and lyrics depend on feature flags.
    assert "MetadataWorker" in starts
    assert "MetadataWorker" in stops
    assert set(starts).issuperset({"MetadataWorker"})
    assert set(stops).issuperset({"MetadataWorker"})


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_lifespan_recreates_scheduler_instances() -> None:
    async with app.router.lifespan_context(app):
        first_runtime = app.state.orchestrator_runtime
        assert first_runtime is not None
        first_scheduler = first_runtime.scheduler
        first_dispatcher = first_runtime.dispatcher

    async with app.router.lifespan_context(app):
        second_runtime = app.state.orchestrator_runtime
        assert second_runtime is not None
        second_scheduler = second_runtime.scheduler
        second_dispatcher = second_runtime.dispatcher

    assert first_scheduler is not second_scheduler
    assert first_dispatcher is not second_dispatcher
