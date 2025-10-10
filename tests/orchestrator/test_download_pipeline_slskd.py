import contextlib
import os
from pathlib import Path
from typing import AsyncIterator

import pytest

from app.integrations.slskd_client import SlskdDownloadEvent, SlskdDownloadStatus
from app.hdm.models import DownloadItem, DownloadWorkItem
from app.hdm.pipeline import (
    DownloadPipelineError,
    RetryableDownloadError,
)
from app.hdm.pipeline_impl import DefaultDownloadPipeline
from app.hdm.recovery import DownloadSidecar


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


class _StubSlskdClient:
    def __init__(self, events: list[SlskdDownloadEvent]) -> None:
        self._events = events

    async def stream_download_events(
        self, *_, **__
    ) -> AsyncIterator[SlskdDownloadEvent]:
        for event in self._events:
            yield event


class _RecordingMonitor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, int]] = []

    async def publish_event(
        self, dedupe_key: str, *, path: Path, bytes_written: int
    ) -> None:
        self.calls.append((dedupe_key, path, bytes_written))


class _NoopTagger:
    class Result:
        applied = False
        codec = None
        bitrate = None
        duration_seconds = None

    def apply_tags(self, _path: Path, _item: DownloadItem) -> "_NoopTagger.Result":
        return self.Result()


class _NoopMover:
    def move(self, source: Path, destination: Path) -> Path:
        return destination


class _NoopDeduper:
    async def acquire_lock(self, _item: DownloadItem):  # pragma: no cover - helper
        class _Lock:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Lock()

    async def lookup_existing(self, _key: str) -> Path | None:
        return None

    def plan_destination(self, item: DownloadItem, path: Path) -> Path:
        return path

    async def register_completion(self, *_: object) -> None:  # pragma: no cover - helper
        return None


class _RecordingSidecars:
    def __init__(self) -> None:
        self.saved: list[DownloadSidecar] = []

    async def save(self, sidecar: DownloadSidecar) -> None:
        self.saved.append(sidecar)


def _make_item() -> DownloadItem:
    return DownloadItem(
        batch_id="batch-1",
        item_id="item-1",
        artist="Artist",
        title="Song",
        album=None,
        isrc=None,
        requested_by="tester",
        priority=1,
        dedupe_key="dedupe-1",
    )


def _make_sidecar(tmp_path: Path) -> DownloadSidecar:
    return DownloadSidecar(
        path=tmp_path / "sidecar.json",
        batch_id="batch-1",
        item_id="item-1",
        dedupe_key="dedupe-1",
        attempt=1,
    )


@pytest.mark.asyncio
async def test_follow_remote_download_records_completion(tmp_path: Path) -> None:
    events = [
        SlskdDownloadEvent("dl-1", SlskdDownloadStatus.ACCEPTED, {}, False),
        SlskdDownloadEvent("dl-1", SlskdDownloadStatus.IN_PROGRESS, {}, False),
        SlskdDownloadEvent(
            "dl-1",
            SlskdDownloadStatus.COMPLETED,
            {"bytes_written": 4096},
            False,
            path=str(tmp_path / "download.flac"),
            bytes_written=4096,
        ),
    ]
    client = _StubSlskdClient(events)
    monitor = _RecordingMonitor()
    pipeline = DefaultDownloadPipeline(
        completion_monitor=monitor,
        tagger=_NoopTagger(),
        mover=_NoopMover(),
        deduper=_NoopDeduper(),
        sidecars=_RecordingSidecars(),
        slskd_client=client,
    )

    item = _make_item()
    work_item = DownloadWorkItem(item=item, attempt=1)
    sidecar = _make_sidecar(tmp_path)

    await pipeline._follow_remote_download(work_item, sidecar)

    assert monitor.calls
    dedupe_key, path, bytes_written = monitor.calls[0]
    assert dedupe_key == "dedupe-1"
    assert bytes_written == 4096
    assert "download.flac" in str(path)


@pytest.mark.asyncio
async def test_follow_remote_download_retryable_failure(tmp_path: Path) -> None:
    events = [
        SlskdDownloadEvent("dl-1", SlskdDownloadStatus.ACCEPTED, {}, False),
        SlskdDownloadEvent(
            "dl-1",
            SlskdDownloadStatus.FAILED,
            {"retry_after_seconds": 2},
            True,
        ),
    ]
    client = _StubSlskdClient(events)
    pipeline = DefaultDownloadPipeline(
        completion_monitor=_RecordingMonitor(),
        tagger=_NoopTagger(),
        mover=_NoopMover(),
        deduper=_NoopDeduper(),
        sidecars=_RecordingSidecars(),
        slskd_client=client,
    )

    item = _make_item()
    work_item = DownloadWorkItem(item=item, attempt=1)
    sidecar = _make_sidecar(tmp_path)

    with pytest.raises(RetryableDownloadError) as exc:
        await pipeline._follow_remote_download(work_item, sidecar)

    assert exc.value.retry_after_seconds == 2


@pytest.mark.asyncio
async def test_follow_remote_download_fatal_failure(tmp_path: Path) -> None:
    events = [
        SlskdDownloadEvent(
            "dl-1",
            SlskdDownloadStatus.FAILED,
            {"error": "permission denied"},
            False,
        ),
    ]
    client = _StubSlskdClient(events)
    pipeline = DefaultDownloadPipeline(
        completion_monitor=_RecordingMonitor(),
        tagger=_NoopTagger(),
        mover=_NoopMover(),
        deduper=_NoopDeduper(),
        sidecars=_RecordingSidecars(),
        slskd_client=client,
    )

    item = _make_item()
    work_item = DownloadWorkItem(item=item, attempt=1)
    sidecar = _make_sidecar(tmp_path)

    with pytest.raises(DownloadPipelineError):
        await pipeline._follow_remote_download(work_item, sidecar)
