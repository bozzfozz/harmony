from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.utils.activity import activity_manager
from app.workers.auto_sync_worker import AutoSyncWorker, TrackInfo


pytestmark = pytest.mark.skip(reason="AutoSync worker archived in MVP")


def _create_track(
    name: str,
    artist: str,
    spotify_id: str = "track-1",
    album_id: str | None = None,
) -> Dict[str, Any]:
    album_identifier = album_id or f"{spotify_id}-album"
    return {
        "name": name,
        "id": spotify_id,
        "artists": [{"name": artist}],
        "album": {"id": album_identifier},
    }


@pytest.fixture(autouse=True)
def clear_activity() -> None:
    activity_manager.clear()


def _build_worker(
    spotify_tracks: list[Dict[str, Any]],
    plex_tracks: list[TrackInfo],
    soulseek_results: Dict[str, Any] | None = None,
    preferences: Dict[str, bool] | None = None,
) -> tuple[AutoSyncWorker, SimpleNamespace, SimpleNamespace, SimpleNamespace, MagicMock]:
    spotify_client = MagicMock()
    spotify_client.get_user_playlists.return_value = {
        "items": [{"id": "pl-1"}],
    }
    spotify_client.get_playlist_items.return_value = {
        "items": [{"track": spotify_tracks[0]}] if spotify_tracks else []
    }
    spotify_client.get_saved_tracks.return_value = {
        "items": [{"track": track} for track in spotify_tracks]
    }

    plex_client = SimpleNamespace()
    plex_client.get_libraries = AsyncMock(
        return_value={
            "MediaContainer": {
                "Directory": [{"type": "artist", "key": "1"}],
            }
        }
    )

    async def _library_items(section_id: str, params: Dict[str, Any] | None = None):
        return {
            "MediaContainer": {
                "Metadata": [
                    {"title": track.title, "grandparentTitle": track.artist}
                    for track in plex_tracks
                ]
            }
        }

    plex_client.get_library_items = AsyncMock(side_effect=_library_items)
    plex_client.get_library_statistics = AsyncMock(return_value={})

    soulseek_client = SimpleNamespace()
    soulseek_client.search = AsyncMock(return_value=soulseek_results or {"results": []})
    soulseek_client.download = AsyncMock(return_value={})

    beets_client = MagicMock()

    preferences_loader = (lambda: dict(preferences)) if preferences is not None else None

    worker = AutoSyncWorker(
        spotify_client,
        plex_client,  # type: ignore[arg-type]
        soulseek_client,  # type: ignore[arg-type]
        beets_client,
        interval_seconds=0.1,
        preferences_loader=preferences_loader,
    )
    return worker, spotify_client, plex_client, soulseek_client, beets_client


@pytest.mark.asyncio
async def test_autosync_no_missing_tracks() -> None:
    track = _create_track("Song A", "Artist")
    worker, spotify_client, plex_client, soulseek_client, beets_client = _build_worker(
        [track],
        [TrackInfo(title="Song A", artist="Artist")],
    )

    await worker.run_once(source="test")

    assert not soulseek_client.search.await_args_list
    assert not beets_client.import_file.called

    statuses = [entry["status"] for entry in reversed(activity_manager.list())]
    assert statuses == [
        "sync_started",
        "spotify_loaded",
        "plex_checked",
        "downloads_requested",
        "beets_imported",
        "sync_completed",
    ]


@pytest.mark.asyncio
async def test_autosync_triggers_download_and_import() -> None:
    missing_track = _create_track("Song B", "Other", spotify_id="track-2")
    worker, spotify_client, plex_client, soulseek_client, beets_client = _build_worker(
        [missing_track],
        [],
        {
            "results": [
                {
                    "username": "dj_user",
                    "files": [
                        {
                            "filename": "Song B.mp3",
                            "path": "/downloads/Song B.mp3",
                        }
                    ],
                }
            ]
        },
    )

    await worker.run_once(source="test")

    soulseek_client.search.assert_awaited()
    soulseek_client.download.assert_awaited()
    beets_client.import_file.assert_called_once_with("/downloads/Song B.mp3", quiet=True)
    plex_client.get_library_statistics.assert_awaited()

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in reversed(entries)]
    assert statuses[-1] == "sync_completed"
    assert "download_enqueued" in statuses
    assert "track_imported" in statuses
    beets_event = next(entry for entry in entries if entry["status"] == "beets_imported")
    assert beets_event["details"]["imported"] == 1
    assert beets_event["details"]["skipped"] == 0


@pytest.mark.asyncio
async def test_autosync_handles_service_errors() -> None:
    worker, spotify_client, plex_client, soulseek_client, beets_client = _build_worker([], [])
    spotify_client.get_user_playlists.side_effect = RuntimeError("spotify down")

    await worker.run_once(source="test")

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in reversed(entries)]
    assert "spotify_unavailable" in statuses
    assert "sync_partial" in statuses
    assert statuses[-1] == "sync_completed"
    completion = next(entry for entry in entries if entry["status"] == "sync_completed")
    assert completion["details"]["counters"]["errors"] == 1

    activity_manager.clear()

    spotify_client.get_user_playlists.side_effect = None
    spotify_client.get_saved_tracks.return_value = {
        "items": [{"track": _create_track("Song C", "Artist C")}]
    }
    plex_client.get_libraries.side_effect = RuntimeError("plex offline")

    await worker.run_once(source="test")

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in reversed(entries)]
    assert "plex_unavailable" in statuses
    assert "sync_partial" in statuses
    assert statuses[-1] == "sync_completed"
    completion = next(entry for entry in entries if entry["status"] == "sync_completed")
    assert completion["details"]["counters"]["errors"] == 1

    activity_manager.clear()

    plex_client.get_libraries.side_effect = None
    plex_client.get_library_items = AsyncMock(return_value={"MediaContainer": {"Metadata": []}})
    soulseek_client.search.return_value = {"results": []}

    await worker.run_once(source="test")

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in reversed(entries)]
    assert "soulseek_no_results" in statuses
    assert "sync_partial" in statuses
    assert statuses[-1] == "sync_completed"
    completion = next(entry for entry in entries if entry["status"] == "sync_completed")
    assert completion["details"]["counters"]["errors"] >= 1


@pytest.mark.asyncio
async def test_activity_feed_order() -> None:
    track = _create_track("Song Z", "Artist Z")
    worker, *_ = _build_worker(
        [track],
        [],
        {
            "results": [
                {
                    "username": "user",
                    "files": [{"filename": "Song Z.flac", "path": "/tmp/songz.flac"}],
                }
            ]
        },
    )

    await worker.run_once(source="test")

    chronological = list(reversed(activity_manager.list()))
    statuses = [entry["status"] for entry in chronological]
    assert statuses[0] == "sync_started"
    assert statuses[1] == "spotify_loaded"
    assert "plex_checked" in statuses
    assert "beets_imported" in statuses
    assert statuses[-1] == "sync_completed"
