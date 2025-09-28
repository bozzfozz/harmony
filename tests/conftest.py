from __future__ import annotations

# ruff: noqa: E402

from pathlib import Path
from typing import Any, Dict, List, Sequence

import os

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HARMONY_API_KEYS", "test-key")
os.environ.setdefault("ALLOWED_ORIGINS", "https://app.local")
os.environ.setdefault("CACHE_ENABLED", "true")
os.environ.setdefault("CACHE_DEFAULT_TTL_S", "30")
os.environ.setdefault("CACHE_MAX_ITEMS", "256")
os.environ.setdefault("CACHEABLE_PATHS", "/|30|60")

import pytest
from app.core.transfers_api import TransfersApiError
from app.db import init_db, reset_engine_for_tests, session_scope
from app.dependencies import (
    get_matching_engine as dependency_matching_engine,
    get_soulseek_client as dependency_soulseek_client,
    get_spotify_client as dependency_spotify_client,
    get_transfers_api as dependency_transfers_api,
)
from app.services.backfill_service import BackfillService
from app.main import app
from app.utils.activity import activity_manager
from app.utils.settings_store import write_setting
from app.workers import BackfillWorker, MatchingWorker, PlaylistSyncWorker, SyncWorker
from app.workers.retry_scheduler import RetryScheduler
from tests.simple_client import SimpleTestClient


class StubSpotifyClient:
    def __init__(self) -> None:
        self.tracks: Dict[str, Dict[str, Any]] = {
            "track-1": {
                "id": "track-1",
                "name": "Test Song",
                "artists": [{"name": "Tester"}],
                "album": {
                    "id": "album-1",
                    "name": "Test Album",
                    "release_date": "1969-01-01",
                    "artists": [{"name": "Tester"}],
                },
                "genre": "rock",
                "duration_ms": 200000,
                "external_ids": {"isrc": "TEST00000001"},
            },
        }
        self.playlists = [
            {"id": "playlist-1", "name": "My Playlist", "tracks": {"total": 1}},
        ]
        self.audio_features: Dict[str, Dict[str, Any]] = {
            "track-1": {"id": "track-1", "danceability": 0.5},
        }
        self.albums: Dict[str, Dict[str, Any]] = {
            "album-1": {
                "id": "album-1",
                "name": "Album",
                "artists": [{"name": "Tester"}],
                "release_date": "1969-02-02",
                "genres": ["rock"],
            }
        }
        self.playlist_items: Dict[str, Dict[str, Any]] = {
            "playlist-1": {"items": [{"track": self.tracks["track-1"]}], "total": 1}
        }
        self.saved_track_ids: set[str] = set()
        self.recommendation_payload: Dict[str, Any] = {"tracks": [], "seeds": []}
        self.followed_artists: List[Dict[str, Any]] = [{"id": "artist-1", "name": "Tester"}]
        self.artist_releases: Dict[str, List[Dict[str, Any]]] = {
            "artist-1": [{"id": "release-1", "name": "Test Release", "album_group": "album"}]
        }
        self.artist_albums: Dict[str, List[Dict[str, Any]]] = {
            "artist-1": [
                {
                    "id": "album-1",
                    "name": "Album",
                    "artists": [{"name": "Tester"}],
                    "release_date": "1969-02-02",
                    "release_date_precision": "day",
                }
            ]
        }
        self.album_tracks: Dict[str, List[Dict[str, Any]]] = {
            "album-1": [dict(self.tracks["track-1"])],
        }
        self.last_requests: Dict[str, Dict[str, Any]] = {}

    def is_authenticated(self) -> bool:
        return True

    def search_tracks(
        self,
        query: str,
        limit: int = 20,
        *,
        genre: str | None = None,
        year: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> Dict[str, Any]:
        self.last_requests["tracks"] = {
            "query": query,
            "genre": genre,
            "year": year,
            "year_from": year_from,
            "year_to": year_to,
        }
        return {"tracks": {"items": list(self.tracks.values())}}

    def find_track_match(
        self,
        *,
        artist: str,
        title: str,
        album: str | None = None,
        duration_ms: int | None = None,
        isrc: str | None = None,
        limit: int = 20,
    ) -> Dict[str, Any] | None:
        for track in self.tracks.values():
            return dict(track)
        return None

    def search_artists(
        self,
        query: str,
        limit: int = 20,
        *,
        genre: str | None = None,
        year: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> Dict[str, Any]:
        self.last_requests["artists"] = {
            "query": query,
            "genre": genre,
            "year": year,
            "year_from": year_from,
            "year_to": year_to,
        }
        return {"artists": {"items": [{"id": "artist-1", "name": "Tester", "genres": ["rock"]}]}}

    def search_albums(
        self,
        query: str,
        limit: int = 20,
        *,
        genre: str | None = None,
        year: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> Dict[str, Any]:
        self.last_requests["albums"] = {
            "query": query,
            "genre": genre,
            "year": year,
            "year_from": year_from,
            "year_to": year_to,
        }
        return {"albums": {"items": [self.albums["album-1"]]}}

    def get_user_playlists(self, limit: int = 50) -> Dict[str, Any]:
        return {"items": [dict(item) for item in self.playlists]}

    def get_artist_albums(
        self,
        artist_id: str,
        include_groups: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Dict[str, Any]]:
        albums = list(self.artist_albums.get(artist_id, []))
        start = max(offset, 0)
        end = start + max(limit, 1)
        return [dict(item) for item in albums[start:end]]

    def get_album_tracks(
        self,
        album_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Dict[str, Any]]:
        tracks = list(self.album_tracks.get(album_id, []))
        start = max(offset, 0)
        end = start + max(limit, 1)
        return [dict(item) for item in tracks[start:end]]

    def get_followed_artists(self, limit: int = 50) -> Dict[str, Any]:
        return {"artists": {"items": [dict(item) for item in self.followed_artists[:limit]]}}

    def get_artist_releases(self, artist_id: str) -> Dict[str, Any]:
        return {"items": [dict(item) for item in self.artist_releases.get(artist_id, [])]}

    def get_track_details(self, track_id: str) -> Dict[str, Any]:
        return self.tracks.get(track_id, {"id": track_id, "name": "Unknown"})

    def get_audio_features(self, track_id: str) -> Dict[str, Any]:
        return self.audio_features.get(track_id, {})

    def get_multiple_audio_features(self, track_ids: list[str]) -> Dict[str, Any]:
        return {
            "audio_features": [
                self.audio_features.get(track_id, {"id": track_id}) for track_id in track_ids
            ]
        }

    def get_playlist_items(
        self, playlist_id: str, limit: int = 100, offset: int = 0
    ) -> Dict[str, Any]:
        payload = self.playlist_items.get(playlist_id, {"items": [], "total": 0})
        items = list(payload.get("items", []))
        start = max(0, offset)
        end = start + max(1, limit)
        return {"items": items[start:end], "total": payload.get("total", len(items))}

    def add_tracks_to_playlist(self, playlist_id: str, track_uris: list[str]) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(playlist_id, {"items": [], "total": 0})
        for uri in track_uris:
            playlist["items"].append({"track": {"uri": uri}})
        playlist["total"] = len(playlist["items"])
        return {"snapshot_id": "mock"}

    def remove_tracks_from_playlist(
        self, playlist_id: str, track_uris: list[str]
    ) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(playlist_id, {"items": [], "total": 0})
        playlist["items"] = [
            item
            for item in playlist["items"]
            if item.get("track", {}).get("uri") not in set(track_uris)
        ]
        playlist["total"] = len(playlist["items"])
        return {"snapshot_id": "mock"}

    def reorder_playlist_items(
        self, playlist_id: str, range_start: int, insert_before: int
    ) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(playlist_id, {"items": [], "total": 0})
        items = playlist["items"]
        if 0 <= range_start < len(items):
            track = items.pop(range_start)
            insert_index = max(0, min(insert_before, len(items)))
            items.insert(insert_index, track)
        playlist["items"] = items
        return {"snapshot_id": "reordered"}

    def get_saved_tracks(self, limit: int = 20) -> Dict[str, Any]:
        saved_items = [
            {"track": self.tracks.get(track_id, {"id": track_id})}
            for track_id in list(self.saved_track_ids)[:limit]
        ]
        return {"items": saved_items, "total": len(self.saved_track_ids)}

    def save_tracks(self, track_ids: list[str]) -> Dict[str, Any]:
        self.saved_track_ids.update(track_ids)
        return {"saved": sorted(self.saved_track_ids)}

    def remove_saved_tracks(self, track_ids: list[str]) -> Dict[str, Any]:
        for track_id in track_ids:
            self.saved_track_ids.discard(track_id)
        return {"saved": sorted(self.saved_track_ids)}

    def get_current_user(self) -> Dict[str, Any]:
        return {"id": "user-1", "display_name": "Harmony Tester"}

    def get_top_tracks(self, limit: int = 20) -> Dict[str, Any]:
        return {"items": list(self.tracks.values())[:limit]}

    def get_top_artists(self, limit: int = 20) -> Dict[str, Any]:
        return {"items": [{"id": "artist-1", "name": "Tester"}]}

    def get_recommendations(
        self,
        seed_tracks: list[str] | None = None,
        seed_artists: list[str] | None = None,
        seed_genres: list[str] | None = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        payload = dict(self.recommendation_payload)
        payload.setdefault("tracks", [])
        payload.setdefault("seeds", [])
        return payload


class StubSoulseekClient:
    def __init__(self) -> None:
        self.downloads: Dict[int, Dict[str, Any]] = {}
        self.queue_positions: Dict[int, Dict[str, Any]] = {}
        self.uploads: Dict[str, Dict[str, Any]] = {
            "up-1": {
                "id": "up-1",
                "filename": "upload.flac",
                "state": "uploading",
                "progress": 40.0,
            },
            "up-2": {
                "id": "up-2",
                "filename": "done.flac",
                "state": "completed",
                "progress": 100.0,
            },
        }
        self.enqueued: list[Dict[str, Any]] = []
        self.user_records: Dict[str, Dict[str, Any]] = {
            "tester": {
                "address": {"host": "127.0.0.1", "port": 2234},
                "browse": {"files": ["song.mp3"]},
                "browsing-status": {"state": "idle"},
                "directory": {"path": "", "files": []},
                "info": {"username": "tester", "slots": 3},
                "status": {"online": True},
            }
        }
        self.search_results: list[Dict[str, Any]] = [
            {
                "username": "user-1",
                "files": [
                    {
                        "id": "soulseek-1",
                        "filename": "Test Song.flac",
                        "title": "Test Song",
                        "artist": "Soulseek Artist",
                        "album": "Soulseek Album",
                        "bitrate": 1000,
                        "format": "flac",
                        "year": 1969,
                        "genre": "rock",
                    },
                    {
                        "id": "soulseek-2",
                        "filename": "Other Track.mp3",
                        "title": "Other Track",
                        "artist": "Soulseek Artist",
                        "album": "Soulseek Album",
                        "bitrate": 320,
                        "format": "mp3",
                        "year": 2005,
                        "genre": "electronic",
                    },
                ],
            }
        ]
        self.last_search_payload: Dict[str, Any] | None = None

    async def get_download_status(self) -> Dict[str, Any]:
        return {"downloads": list(self.downloads.values())}

    async def search(
        self,
        query: str,
        *,
        min_bitrate: int | None = None,
        format_priority: Sequence[str] | None = None,
    ) -> Dict[str, Any]:
        self.last_search_payload = {
            "query": query,
            "min_bitrate": min_bitrate,
            "format_priority": list(format_priority) if format_priority else None,
        }
        matches: list[Dict[str, Any]] = []
        query_lower = query.lower()
        for result in self.search_results:
            files = []
            for file_info in result.get("files", []):
                title = str(file_info.get("title") or file_info.get("filename") or "").lower()
                if query_lower in title:
                    files.append(dict(file_info))
            if files:
                entry = dict(result)
                entry["files"] = files
                matches.append(entry)
        return {"results": matches}

    def normalise_search_results(self, payload: Any) -> list[Dict[str, Any]]:
        if isinstance(payload, dict):
            results = payload.get("results") or []
        elif isinstance(payload, list):
            results = payload
        else:
            results = []
        flattened: list[Dict[str, Any]] = []
        for entry in results:
            if not isinstance(entry, dict):
                continue
            username = entry.get("username")
            for file_info in entry.get("files", []):
                if not isinstance(file_info, dict):
                    continue
                flattened.append(
                    {
                        "id": file_info.get("id"),
                        "title": file_info.get("title") or file_info.get("filename"),
                        "artists": ([file_info.get("artist")] if file_info.get("artist") else []),
                        "album": file_info.get("album"),
                        "year": file_info.get("year"),
                        "duration_ms": file_info.get("duration_ms"),
                        "bitrate": file_info.get("bitrate"),
                        "format": file_info.get("format"),
                        "genres": ([file_info.get("genre")] if file_info.get("genre") else []),
                        "extra": {
                            "username": username,
                            "path": file_info.get("filename"),
                            "size": file_info.get("size"),
                        },
                    }
                )
        return flattened

    async def download(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        for file_info in payload.get("files", []):
            identifier = int(file_info.get("download_id", 0))
            if identifier <= 0:
                continue
            entry = {
                "id": identifier,
                "filename": file_info.get("filename", "unknown"),
                "progress": 0.0,
                "state": "queued",
            }
            self.downloads[identifier] = entry
        return {"status": "queued"}

    async def cancel_download(self, download_id: str) -> Dict[str, Any]:
        identifier = int(download_id)
        if identifier in self.downloads:
            self.downloads[identifier]["state"] = "failed"
        return {"cancelled": download_id}

    async def get_download(self, download_id: str) -> Dict[str, Any]:
        identifier = int(download_id)
        return self.downloads.get(identifier, {"id": identifier, "state": "unknown"})

    async def get_all_downloads(self) -> list[Dict[str, Any]]:
        return list(self.downloads.values())

    async def remove_completed_downloads(self) -> Dict[str, Any]:
        before = len(self.downloads)
        self.downloads = {k: v for k, v in self.downloads.items() if v.get("state") != "completed"}
        removed = before - len(self.downloads)
        return {"removed": removed}

    async def get_queue_position(self, download_id: str) -> Dict[str, Any]:
        identifier = int(download_id)
        return self.queue_positions.get(identifier, {"position": None})

    async def enqueue(self, username: str, files: list[Dict[str, Any]]) -> Dict[str, Any]:
        job = {"username": username, "files": files}
        self.enqueued.append(job)
        return {"status": "enqueued", "job": job}

    async def cancel_upload(self, upload_id: str) -> Dict[str, Any]:
        upload = self.uploads.get(upload_id)
        if upload:
            upload["state"] = "cancelled"
        return {"cancelled": upload_id}

    async def get_upload(self, upload_id: str) -> Dict[str, Any]:
        return self.uploads.get(upload_id, {"id": upload_id, "state": "unknown"})

    async def get_uploads(self) -> list[Dict[str, Any]]:
        return [upload for upload in self.uploads.values() if upload.get("state") != "completed"]

    async def get_all_uploads(self) -> list[Dict[str, Any]]:
        return list(self.uploads.values())

    async def remove_completed_uploads(self) -> Dict[str, Any]:
        before = len(self.uploads)
        self.uploads = {k: v for k, v in self.uploads.items() if v.get("state") != "completed"}
        removed = before - len(self.uploads)
        return {"removed": removed}

    async def user_address(self, username: str) -> Dict[str, Any]:
        record = self.user_records.get(username, {})
        return record.get("address", {"host": None, "port": None})

    async def user_browse(self, username: str) -> Dict[str, Any]:
        record = self.user_records.get(username, {})
        return record.get("browse", {"files": []})

    async def user_browsing_status(self, username: str) -> Dict[str, Any]:
        record = self.user_records.get(username, {})
        return record.get("browsing-status", {"state": "unknown"})

    async def user_directory(self, username: str, path: str) -> Dict[str, Any]:
        record = self.user_records.setdefault(username, {})
        directory = record.get("directory", {"path": path, "files": []})
        directory = dict(directory)
        directory["path"] = path
        return directory

    async def user_info(self, username: str) -> Dict[str, Any]:
        record = self.user_records.get(username, {})
        return record.get("info", {"username": username})

    async def user_status(self, username: str) -> Dict[str, Any]:
        record = self.user_records.get(username, {})
        return record.get("status", {"online": False})

    def set_status(
        self,
        download_id: int,
        *,
        progress: float | None = None,
        state: str | None = None,
    ) -> None:
        entry = self.downloads.setdefault(
            download_id,
            {
                "id": download_id,
                "filename": f"download-{download_id}",
                "progress": 0.0,
                "state": "queued",
            },
        )
        if progress is not None:
            entry["progress"] = progress
        if state is not None:
            entry["state"] = state


class StubTransfersApi:
    def __init__(self, soulseek: StubSoulseekClient) -> None:
        self._soulseek = soulseek
        self.cancelled: list[int] = []
        self.enqueued: list[Dict[str, Any]] = []
        self.raise_cancel: TransfersApiError | None = None
        self.raise_enqueue: TransfersApiError | None = None

    async def cancel_download(self, download_id: int | str) -> Dict[str, Any]:
        if self.raise_cancel is not None:
            raise self.raise_cancel
        identifier = int(download_id)
        self.cancelled.append(identifier)
        return await self._soulseek.cancel_download(str(identifier))

    async def enqueue(self, *, username: str, files: list[Dict[str, Any]]) -> Dict[str, Any]:
        if self.raise_enqueue is not None:
            raise self.raise_enqueue
        job = {"username": username, "files": files}
        self.enqueued.append(job)
        return await self._soulseek.enqueue(username, files)


class StubLyricsWorker:
    def __init__(self) -> None:
        self.jobs: list[tuple[int | None, str, Dict[str, Any]]] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def enqueue(
        self,
        download_id: int | None,
        file_path: str,
        track_info: Dict[str, Any],
    ) -> None:
        self.jobs.append((download_id, file_path, dict(track_info)))


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> None:
    from app import dependencies as deps

    deps.get_app_config.cache_clear()
    deps.get_spotify_client.cache_clear()
    deps.get_soulseek_client.cache_clear()
    deps.get_transfers_api.cache_clear()
    deps.get_matching_engine.cache_clear()

    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("ENABLE_ARTWORK", "1")
    monkeypatch.setenv("ENABLE_LYRICS", "1")
    db_dir = tmp_path_factory.mktemp("db")
    db_path = db_dir / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_engine_for_tests()
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = db_path.with_name(f"{db_path.name}{suffix}")
        if candidate.exists():
            candidate.unlink()
    init_db()
    write_setting("SPOTIFY_CLIENT_ID", "stub-client")
    write_setting("SPOTIFY_CLIENT_SECRET", "stub-secret")
    write_setting("SPOTIFY_REDIRECT_URI", "http://localhost/callback")
    write_setting("SLSKD_URL", "http://localhost:5030")
    yield
    reset_engine_for_tests()
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = db_path.with_name(f"{db_path.name}{suffix}")
        if candidate.exists():
            candidate.unlink()


@pytest.fixture(autouse=True)
def reset_activity_manager() -> None:
    activity_manager.clear()
    yield
    activity_manager.clear()


@pytest.fixture
def db_session():
    with session_scope() as session:
        yield session


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> SimpleTestClient:
    stub_spotify = StubSpotifyClient()
    stub_soulseek = StubSoulseekClient()
    stub_transfers = StubTransfersApi(stub_soulseek)
    stub_lyrics = StubLyricsWorker()
    engine = dependency_matching_engine()

    async def noop_start(self) -> None:  # type: ignore[override]
        return None

    async def noop_stop(self) -> None:  # type: ignore[override]
        return None

    # Prevent worker tasks during tests
    monkeypatch.setattr(SyncWorker, "start", noop_start)
    monkeypatch.setattr(MatchingWorker, "start", noop_start)
    monkeypatch.setattr(PlaylistSyncWorker, "start", noop_start)
    monkeypatch.setattr(RetryScheduler, "start", noop_start)
    monkeypatch.setattr(SyncWorker, "stop", noop_stop)
    monkeypatch.setattr(MatchingWorker, "stop", noop_stop)
    monkeypatch.setattr(PlaylistSyncWorker, "stop", noop_stop)
    monkeypatch.setattr(RetryScheduler, "stop", noop_stop)

    from app import dependencies as deps

    monkeypatch.setattr(deps, "get_spotify_client", lambda: stub_spotify)
    monkeypatch.setattr(deps, "get_soulseek_client", lambda: stub_soulseek)
    monkeypatch.setattr(deps, "get_transfers_api", lambda: stub_transfers)
    monkeypatch.setattr(deps, "get_matching_engine", lambda: engine)

    app.dependency_overrides[dependency_spotify_client] = lambda: stub_spotify
    app.dependency_overrides[dependency_soulseek_client] = lambda: stub_soulseek
    app.dependency_overrides[dependency_transfers_api] = lambda: stub_transfers
    app.dependency_overrides[dependency_matching_engine] = lambda: engine

    app.state.soulseek_stub = stub_soulseek
    app.state.transfers_stub = stub_transfers
    app.state.spotify_stub = stub_spotify
    app.state.lyrics_worker = stub_lyrics
    app.state.sync_worker = SyncWorker(stub_soulseek, lyrics_worker=stub_lyrics)
    app.state.retry_scheduler = RetryScheduler(app.state.sync_worker)
    app.state.playlist_worker = PlaylistSyncWorker(stub_spotify, interval_seconds=0.1)

    with SimpleTestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def backfill_runtime(client: SimpleTestClient):
    from app import dependencies as deps

    config = deps.get_app_config()
    spotify_client = client.app.state.spotify_stub
    service = BackfillService(config.spotify, spotify_client)
    worker = BackfillWorker(service)
    client.app.state.backfill_service = service
    client.app.state.backfill_worker = worker
    client._loop.run_until_complete(worker.start())
    try:
        yield service, worker
        client._loop.run_until_complete(worker.wait_until_idle())
    finally:
        client._loop.run_until_complete(worker.stop())
        client.app.state.backfill_worker = None
        client.app.state.backfill_service = None
