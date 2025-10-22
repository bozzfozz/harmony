from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from app.config import DEFAULT_PLAYLIST_SYNC_STALE_AFTER
from app.core.spotify_client import SpotifyClient
from app.db import init_db, session_scope
from app.models import Playlist
from app.workers.playlist_sync_worker import PlaylistSyncWorker


def _worker(*, stale_after: timedelta = DEFAULT_PLAYLIST_SYNC_STALE_AFTER) -> PlaylistSyncWorker:
    client = cast(SpotifyClient, object())
    return PlaylistSyncWorker(client, stale_after=stale_after)


def test_persist_playlists_populates_metadata() -> None:
    init_db()
    worker = _worker()
    timestamp = datetime(2023, 9, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    payload = {
        "id": "playlist-1",
        "name": "Example",
        "tracks": {"total": 15},
        "owner": {"display_name": "Owner A", "id": "owner-a"},
        "followers": {"total": 42},
        "snapshot_id": "snapshot-1",
        "public": True,
        "collaborative": False,
    }

    processed = worker._persist_playlists([payload], timestamp, None)

    assert processed == 1
    with session_scope() as session:
        record = session.get(Playlist, "playlist-1")
        assert record is not None
        assert record.metadata_json["owner"] == "Owner A"
        assert record.metadata_json["owner_id"] == "owner-a"
        assert record.metadata_json["followers"] == 42
        assert record.metadata_json["snapshot_id"] == "snapshot-1"
        assert record.metadata_json["sync_status"] == "fresh"
        assert record.metadata_json["sync_status_reason"] == "synced_recently"
        assert record.metadata_json["synced_at"] == timestamp.isoformat()


def test_persist_playlists_marks_stale_on_snapshot_change() -> None:
    init_db()
    worker = _worker()
    timestamp = datetime(2023, 9, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    first_payload = {
        "id": "playlist-2",
        "name": "Daily Mix",
        "tracks": {"total": 10},
        "owner": {"display_name": "Owner B", "id": "owner-b"},
        "followers": {"total": 5},
        "snapshot_id": "snapshot-1",
    }
    worker._persist_playlists([first_payload], timestamp, None)

    second_payload = dict(first_payload, snapshot_id="snapshot-2", followers={"total": 7})
    worker._persist_playlists([second_payload], timestamp, None)

    with session_scope() as session:
        record = session.get(Playlist, "playlist-2")
        assert record is not None
        assert record.metadata_json["followers"] == 7
        assert record.metadata_json["sync_status"] == "stale"
        assert record.metadata_json["sync_status_reason"] == "snapshot_changed"
        assert record.metadata_json["snapshot_id"] == "snapshot-2"
        assert record.metadata_json["synced_at"] == timestamp.isoformat()


def test_persist_playlists_marks_stale_when_snapshot_missing() -> None:
    init_db()
    worker = _worker()
    timestamp = datetime(2023, 9, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    base_payload = {
        "id": "playlist-3",
        "name": "Lo-Fi",
        "tracks": {"total": 8},
        "snapshot_id": "snapshot-1",
    }
    worker._persist_playlists([base_payload], timestamp, None)

    missing_snapshot = dict(base_payload)
    missing_snapshot.pop("snapshot_id")
    worker._persist_playlists([missing_snapshot], timestamp, None)

    with session_scope() as session:
        record = session.get(Playlist, "playlist-3")
        assert record is not None
        assert record.metadata_json["sync_status"] == "stale"
        assert record.metadata_json["sync_status_reason"] == "missing_snapshot"
        assert record.metadata_json.get("snapshot_id") is None


def test_persist_playlists_marks_stale_when_sync_gap_exceeds_window() -> None:
    init_db()
    worker = _worker()
    base = datetime(2023, 9, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    payload = {
        "id": "playlist-4",
        "name": "Morning Mix",
        "tracks": {"total": 20},
        "snapshot_id": "snapshot-1",
    }

    worker._persist_playlists([payload], base, None)

    late = base + DEFAULT_PLAYLIST_SYNC_STALE_AFTER + timedelta(minutes=1)
    worker._persist_playlists([payload], late, None)

    with session_scope() as session:
        record = session.get(Playlist, "playlist-4")
        assert record is not None
        assert record.metadata_json["sync_status"] == "stale"
        assert record.metadata_json["sync_status_reason"] == "sync_gap"
        assert record.metadata_json["synced_at"] == late.isoformat()

    catch_up = late + timedelta(minutes=5)
    worker._persist_playlists([payload], catch_up, None)

    with session_scope() as session:
        record = session.get(Playlist, "playlist-4")
        assert record is not None
        assert record.metadata_json["sync_status"] == "fresh"
        assert record.metadata_json["sync_status_reason"] == "synced_recently"
        assert record.metadata_json["synced_at"] == catch_up.isoformat()


def test_playlist_sync_respects_configured_stale_window() -> None:
    """Ensure PLAYLIST_SYNC_STALE_AFTER_HOURS adjusts the stale detection gap."""

    init_db()
    short_window = timedelta(minutes=30)
    worker = _worker(stale_after=short_window)
    base = datetime(2023, 9, 1, 8, 0, tzinfo=UTC).replace(tzinfo=None)
    payload = {
        "id": "playlist-5",
        "name": "Afternoon Flow",
        "tracks": {"total": 12},
        "snapshot_id": "snapshot-1",
    }

    worker._persist_playlists([payload], base, None)

    within_window = base + timedelta(minutes=25)
    worker._persist_playlists([payload], within_window, None)

    with session_scope() as session:
        record = session.get(Playlist, "playlist-5")
        assert record is not None
        assert record.metadata_json["sync_status"] == "fresh"
        assert record.metadata_json["sync_status_reason"] == "synced_recently"

    beyond_window = within_window + short_window + timedelta(minutes=1)
    worker._persist_playlists([payload], beyond_window, None)

    with session_scope() as session:
        record = session.get(Playlist, "playlist-5")
        assert record is not None
        assert record.metadata_json["sync_status"] == "stale"
        assert record.metadata_json["sync_status_reason"] == "sync_gap"
        assert record.metadata_json["synced_at"] == beyond_window.isoformat()
