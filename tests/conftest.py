from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from app.core.transfers_api import TransfersApiError
from app.db import init_db, reset_engine_for_tests
from app.dependencies import (
    get_matching_engine as dependency_matching_engine,
    get_plex_client as dependency_plex_client,
    get_soulseek_client as dependency_soulseek_client,
    get_spotify_client as dependency_spotify_client,
    get_transfers_api as dependency_transfers_api,
)
from app.main import app
from app.utils.activity import activity_manager
from app.utils.settings_store import write_setting
from app.workers import MatchingWorker, PlaylistSyncWorker, ScanWorker, SyncWorker
from tests.simple_client import SimpleTestClient


class StubSpotifyClient:
    def __init__(self) -> None:
        self.tracks: Dict[str, Dict[str, Any]] = {
            "track-1": {"id": "track-1", "name": "Test Song", "artists": [{"name": "Tester"}], "duration_ms": 200000},
        }
        self.playlists = [
            {"id": "playlist-1", "name": "My Playlist", "tracks": {"total": 1}},
        ]
        self.audio_features: Dict[str, Dict[str, Any]] = {
            "track-1": {"id": "track-1", "danceability": 0.5},
        }
        self.playlist_items: Dict[str, Dict[str, Any]] = {
            "playlist-1": {"items": [{"track": self.tracks["track-1"]}], "total": 1}
        }
        self.saved_track_ids: set[str] = set()
        self.recommendation_payload: Dict[str, Any] = {"tracks": [], "seeds": []}
        self.followed_artists: List[Dict[str, Any]] = [
            {"id": "artist-1", "name": "Tester"}
        ]
        self.artist_releases: Dict[str, List[Dict[str, Any]]] = {
            "artist-1": [
                {"id": "release-1", "name": "Test Release", "album_group": "album"}
            ]
        }

    def is_authenticated(self) -> bool:
        return True

    def search_tracks(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return {"tracks": {"items": list(self.tracks.values())}}

    def search_artists(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return {"artists": {"items": [{"id": "artist-1", "name": "Tester"}]}}

    def search_albums(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return {"albums": {"items": [{"id": "album-1", "name": "Album", "artists": [{"name": "Tester"}]}]}}

    def get_user_playlists(self, limit: int = 50) -> Dict[str, Any]:
        return {"items": [dict(item) for item in self.playlists]}

    def get_followed_artists(self, limit: int = 50) -> Dict[str, Any]:
        return {
            "artists": {
                "items": [dict(item) for item in self.followed_artists[:limit]]
            }
        }

    def get_artist_releases(self, artist_id: str) -> Dict[str, Any]:
        return {
            "items": [dict(item) for item in self.artist_releases.get(artist_id, [])]
        }

    def get_track_details(self, track_id: str) -> Dict[str, Any]:
        return self.tracks.get(track_id, {"id": track_id, "name": "Unknown"})

    def get_audio_features(self, track_id: str) -> Dict[str, Any]:
        return self.audio_features.get(track_id, {})

    def get_multiple_audio_features(self, track_ids: list[str]) -> Dict[str, Any]:
        return {
            "audio_features": [self.audio_features.get(track_id, {"id": track_id}) for track_id in track_ids]
        }

    def get_playlist_items(self, playlist_id: str, limit: int = 100) -> Dict[str, Any]:
        return self.playlist_items.get(playlist_id, {"items": [], "total": 0})

    def add_tracks_to_playlist(self, playlist_id: str, track_uris: list[str]) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(playlist_id, {"items": [], "total": 0})
        for uri in track_uris:
            playlist["items"].append({"track": {"uri": uri}})
        playlist["total"] = len(playlist["items"])
        return {"snapshot_id": "mock"}

    def remove_tracks_from_playlist(self, playlist_id: str, track_uris: list[str]) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(playlist_id, {"items": [], "total": 0})
        playlist["items"] = [
            item for item in playlist["items"] if item.get("track", {}).get("uri") not in set(track_uris)
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


class StubPlexClient:
    def __init__(self) -> None:
        self.libraries = {
            "MediaContainer": {
                "Directory": [
                    {"key": "1", "type": "artist", "title": "Music"},
                ]
            }
        }
        self.library_items = {
            ("1", "10"): {
                "MediaContainer": {"totalSize": 2, "Metadata": [{"ratingKey": "a"}, {"ratingKey": "b"}]}
            },
            ("1", "9"): {
                "MediaContainer": {"totalSize": 3, "Metadata": [{"ratingKey": "a"}]}
            },
            ("1", "8"): {
                "MediaContainer": {"totalSize": 5, "Metadata": [{"ratingKey": "t"}]}
            },
        }
        self.metadata = {"100": {"title": "Test Item", "year": 2020}}
        self.sessions = {"MediaContainer": {"size": 1, "Metadata": [{"title": "Session"}]}}
        self.session_history = {"MediaContainer": {"size": 1, "Metadata": [{"title": "History"}]}}
        self.playlists = {"MediaContainer": {"size": 1, "Metadata": [{"title": "Playlist"}]}}
        self.created_playlists: list[dict[str, Any]] = []
        self.playqueues: Dict[str, Any] = {}
        self.timeline_updates: list[dict[str, Any]] = []
        self.scrobbles: list[dict[str, Any]] = []
        self.unscrobbles: list[dict[str, Any]] = []
        self.ratings: list[dict[str, Any]] = []
        self.tags: Dict[str, Dict[str, list[str]]] = {}
        self.devices = {"MediaContainer": {"Device": [{"name": "Player"}]}}
        self.dvr = {"MediaContainer": {"Directory": [{"name": "DVR"}]}}
        self.livetv = {"MediaContainer": {"Directory": [{"name": "Channel"}]}}

    async def get_sessions(self) -> Dict[str, Any]:
        return self.sessions

    async def get_library_statistics(self) -> Dict[str, int]:
        return {"artists": 2, "albums": 3, "tracks": 5}

    async def get_libraries(self, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.libraries

    async def get_library_items(self, section_id: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        type_value = (params or {}).get("type", "")
        return self.library_items.get((section_id, type_value), {"MediaContainer": {"Metadata": []}})

    async def get_metadata(self, item_id: str) -> Dict[str, Any]:
        return self.metadata[item_id]

    async def get_session_history(self, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.session_history

    async def get_timeline(self, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return {"timeline": params or {}}

    async def update_timeline(self, data: Dict[str, Any]) -> str:
        self.timeline_updates.append(data)
        return "ok"

    async def scrobble(self, data: Dict[str, Any]) -> str:
        self.scrobbles.append(data)
        return "ok"

    async def unscrobble(self, data: Dict[str, Any]) -> str:
        self.unscrobbles.append(data)
        return "ok"

    async def get_playlists(self) -> Dict[str, Any]:
        return self.playlists

    async def create_playlist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.created_playlists.append(payload)
        return {"status": "created", "payload": payload}

    async def update_playlist(self, playlist_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "updated", "id": playlist_id, "payload": payload}

    async def delete_playlist(self, playlist_id: str) -> Dict[str, Any]:
        return {"status": "deleted", "id": playlist_id}

    async def create_playqueue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        identifier = str(len(self.playqueues) + 1)
        self.playqueues[identifier] = payload
        return {"playQueueID": identifier, "payload": payload}

    async def get_playqueue(self, playqueue_id: str) -> Dict[str, Any]:
        return self.playqueues.get(playqueue_id, {})

    async def rate_item(self, item_id: str, rating: int) -> str:
        self.ratings.append({"key": item_id, "rating": rating})
        return "ok"

    async def sync_tags(self, item_id: str, tags: Dict[str, list[str]]) -> Dict[str, Any]:
        self.tags[item_id] = tags
        return {"status": "tags-updated", "id": item_id, "tags": tags}

    async def get_devices(self) -> Dict[str, Any]:
        return self.devices

    async def get_dvr(self) -> Dict[str, Any]:
        return self.dvr

    async def get_live_tv(self, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.livetv

    @asynccontextmanager
    async def listen_notifications(self):  # pragma: no cover - exercised via tests
        class _Message:
            def __init__(self) -> None:
                self.type = type("Type", (), {"name": "TEXT"})
                self.data = "event"

        class _Websocket:
            def __init__(self) -> None:
                self._sent = False

            def exception(self):
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._sent:
                    raise StopAsyncIteration
                self._sent = True
                return _Message()

        yield _Websocket()


class StubSoulseekClient:
    def __init__(self) -> None:
        self.downloads: Dict[int, Dict[str, Any]] = {}
        self.queue_positions: Dict[int, Dict[str, Any]] = {}
        self.uploads: Dict[str, Dict[str, Any]] = {
            "up-1": {"id": "up-1", "filename": "upload.flac", "state": "uploading", "progress": 40.0},
            "up-2": {"id": "up-2", "filename": "done.flac", "state": "completed", "progress": 100.0},
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

    async def get_download_status(self) -> Dict[str, Any]:
        return {"downloads": list(self.downloads.values())}

    async def search(self, query: str) -> Dict[str, Any]:
        return {"results": [query]}

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


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    reset_engine_for_tests()
    for suffix in ("", "-journal", "-wal", "-shm"):
        db_path = Path(f"test.db{suffix}")
        if db_path.exists():
            db_path.unlink()
    init_db()
    write_setting("SPOTIFY_CLIENT_ID", "stub-client")
    write_setting("SPOTIFY_CLIENT_SECRET", "stub-secret")
    write_setting("SPOTIFY_REDIRECT_URI", "http://localhost/callback")
    write_setting("PLEX_BASE_URL", "http://plex.local")
    write_setting("PLEX_TOKEN", "token")
    write_setting("SLSKD_URL", "http://localhost:5030")
    yield
    reset_engine_for_tests()
    for suffix in ("", "-journal", "-wal", "-shm"):
        db_path = Path(f"test.db{suffix}")
        if db_path.exists():
            db_path.unlink()


@pytest.fixture(autouse=True)
def reset_activity_manager() -> None:
    activity_manager.clear()
    yield
    activity_manager.clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> SimpleTestClient:
    stub_spotify = StubSpotifyClient()
    stub_plex = StubPlexClient()
    stub_soulseek = StubSoulseekClient()
    stub_transfers = StubTransfersApi(stub_soulseek)
    engine = dependency_matching_engine()

    async def noop_start(self) -> None:  # type: ignore[override]
        return None

    async def noop_stop(self) -> None:  # type: ignore[override]
        return None

    # Prevent worker tasks during tests
    monkeypatch.setattr(SyncWorker, "start", noop_start)
    monkeypatch.setattr(MatchingWorker, "start", noop_start)
    monkeypatch.setattr(ScanWorker, "start", noop_start)
    monkeypatch.setattr(PlaylistSyncWorker, "start", noop_start)
    monkeypatch.setattr(SyncWorker, "stop", noop_stop)
    monkeypatch.setattr(MatchingWorker, "stop", noop_stop)
    monkeypatch.setattr(ScanWorker, "stop", noop_stop)
    monkeypatch.setattr(PlaylistSyncWorker, "stop", noop_stop)

    from app import dependencies as deps

    monkeypatch.setattr(deps, "get_spotify_client", lambda: stub_spotify)
    monkeypatch.setattr(deps, "get_plex_client", lambda: stub_plex)
    monkeypatch.setattr(deps, "get_soulseek_client", lambda: stub_soulseek)
    monkeypatch.setattr(deps, "get_transfers_api", lambda: stub_transfers)
    monkeypatch.setattr(deps, "get_matching_engine", lambda: engine)

    app.dependency_overrides[dependency_spotify_client] = lambda: stub_spotify
    app.dependency_overrides[dependency_plex_client] = lambda: stub_plex
    app.dependency_overrides[dependency_soulseek_client] = lambda: stub_soulseek
    app.dependency_overrides[dependency_transfers_api] = lambda: stub_transfers
    app.dependency_overrides[dependency_matching_engine] = lambda: engine

    app.state.soulseek_stub = stub_soulseek
    app.state.transfers_stub = stub_transfers
    app.state.plex_stub = stub_plex
    app.state.spotify_stub = stub_spotify
    app.state.sync_worker = SyncWorker(stub_soulseek)
    app.state.playlist_worker = PlaylistSyncWorker(stub_spotify, interval_seconds=0.1)

    with SimpleTestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
