"""Tests covering filesystem-based deduplication coordination."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.hdm.dedup import DeduplicationManager
from app.hdm.models import DownloadItem
from tests.orchestrator._flow_fixtures import (  # noqa: F401
    configure_environment,
    reset_activity_manager,
)


def _make_item(*, dedupe_key: str = "dedupe") -> DownloadItem:
    return DownloadItem(
        batch_id="batch",
        item_id="item",
        artist="Artist",
        title="Title",
        album="Album",
        isrc=None,
        requested_by="tester",
        priority=0,
        dedupe_key=dedupe_key,
    )


@pytest.mark.asyncio
async def test_acquire_lock_serialises_tasks(tmp_path: Path) -> None:
    manager = DeduplicationManager(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        move_template="{artist}/{title}.{extension}",
    )
    item = _make_item()

    release_first = asyncio.Event()
    acquired_second = asyncio.Event()

    async def first_lock() -> None:
        async with await manager.acquire_lock(item):
            await asyncio.sleep(0)
            release_first.set()
            await asyncio.sleep(0.05)

    async def second_lock() -> None:
        await release_first.wait()
        async with await manager.acquire_lock(item):
            acquired_second.set()

    task_one = asyncio.create_task(first_lock())
    task_two = asyncio.create_task(second_lock())

    await asyncio.wait_for(acquired_second.wait(), timeout=5)
    await asyncio.gather(task_one, task_two)

    lock_path = (tmp_path / "state" / "locks" / f"{item.dedupe_key}.lock")
    assert lock_path.exists()


@pytest.mark.asyncio
async def test_register_and_lookup_completion(tmp_path: Path) -> None:
    manager = DeduplicationManager(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        move_template="{artist}/{title}.{extension}",
    )
    item = _make_item()
    final_path = tmp_path / "library" / "Artist" / "Title.flac"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text("ok", encoding="utf-8")

    await manager.register_completion(item.dedupe_key, final_path)

    index_path = tmp_path / "state" / "dedupe_index.json"
    content = json.loads(index_path.read_text(encoding="utf-8"))
    assert content[item.dedupe_key] == str(final_path)

    existing = await manager.lookup_existing(item.dedupe_key)
    assert existing == final_path


@pytest.mark.asyncio
async def test_plan_destination_sanitises_metadata(tmp_path: Path) -> None:
    manager = DeduplicationManager(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        move_template="{artist}/{album}/{title}.{extension}",
    )
    source = tmp_path / "downloads" / "FILE.MP3"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"data")
    item = _make_item(dedupe_key="Key/With:Unsafe")

    destination = manager.plan_destination(item, source)

    assert destination.is_relative_to(tmp_path / "music")
    assert destination.suffix == ".mp3"
    assert "Unsafe" not in destination.name
