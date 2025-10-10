"""Tests ensuring Harmony Download Manager recovery handles crash scenarios and size stability."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.hdm.completion import (
    CompletionEventBus,
    DownloadCompletionEvent,
    DownloadCompletionMonitor,
)
from app.hdm.models import DownloadItem
from app.hdm.recovery import (
    HdmRecovery,
    SidecarStore,
)
from tests.orchestrator._flow_fixtures import (  # noqa: F401
    configure_environment,
    reset_activity_manager,
)


def _item_for_sidecar() -> DownloadItem:
    return DownloadItem(
        batch_id="batch",
        item_id="item",
        artist="Artist",
        title="Track",
        album=None,
        isrc=None,
        requested_by="tester",
        priority=0,
        dedupe_key="dedupe",
    )


@pytest.mark.asyncio
async def test_completion_monitor_waits_for_size_stability(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    event_bus = CompletionEventBus()
    monitor = DownloadCompletionMonitor(
        downloads_dir=downloads_dir,
        size_stable_seconds=1,
        event_bus=event_bus,
        poll_interval=0.05,
    )

    path = downloads_dir / "artist-track.flac"

    path.touch()

    async def writer() -> None:
        with path.open("wb") as handle:
            for chunk in [b"a" * 256, b"b" * 256, b"c" * 256]:
                handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                await asyncio.sleep(0.1)

    writer_task = asyncio.create_task(writer())
    size = await monitor.ensure_stable(path)
    await writer_task

    assert size == path.stat().st_size


@pytest.mark.asyncio
async def test_recovery_scans_sidecars_and_publishes_events(tmp_path: Path) -> None:
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    sidecar_dir = tmp_path / "sidecars"
    bus = CompletionEventBus()

    class DummyMonitor:
        def __init__(self) -> None:
            self.paths: list[Path] = []

        async def ensure_stable(self, path: Path) -> int:  # pragma: no cover - runtime exercised
            self.paths.append(path)
            return int(path.stat().st_size)

    monitor = DummyMonitor()
    recovery = HdmRecovery(
        size_stable_seconds=1,
        sidecars=SidecarStore(sidecar_dir),
        completion_monitor=monitor,  # type: ignore[arg-type]
        event_bus=bus,
        poll_interval=0.05,
    )

    item = _item_for_sidecar()
    store = recovery._sidecars
    sidecar = await store.load(item, attempt=1)
    file_path = downloads_dir / "file.flac"
    file_path.write_bytes(b"payload")
    sidecar.mark(status="downloading", source_path=file_path)
    await store.save(sidecar)

    queue = await bus.subscribe(item.dedupe_key)
    await recovery._scan()

    event = queue.get_nowait()
    assert isinstance(event, DownloadCompletionEvent)
    assert event.path == file_path
    assert monitor.paths == [file_path]

    await bus.unsubscribe(item.dedupe_key, queue)
