from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from app.dependencies import (
    get_matching_engine as dependency_matching_engine,
    get_plex_client as dependency_plex_client,
    get_soulseek_client as dependency_soulseek_client,
    get_spotify_client as dependency_spotify_client,
)
from app.main import app
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

    def get_track_details(self, track_id: str) -> Dict[str, Any]:
        return self.tracks.get(track_id, {"id": track_id, "name": "Unknown"})


class StubPlexClient:
    def __init__(self) -> None:
        self.artists = [
            {"id": "1", "name": "Tester"},
            {"id": "2", "name": "Another Tester"},
        ]
        self.albums_by_artist = {
            "1": [{"id": "10", "title": "Album", "year": 2020}],
            "2": [
                {"id": "20", "title": "Another Album", "year": 2019},
            ],
        }
        self.tracks_by_album = {
            "10": [{"id": "100", "title": "Test Song", "duration": 200000}],
            "20": [
                {"id": "200", "title": "Second Song", "duration": 210000},
                {"id": "201", "title": "Third Song", "duration": 185000},
            ],
        }

    def is_connected(self) -> bool:
        return True

    def get_all_artists(self) -> list:
        return self.artists

    def get_albums_by_artist(self, artist_id: str) -> list:
        return self.albums_by_artist.get(artist_id, [])

    def get_tracks_by_album(self, album_id: str) -> list:
        return self.tracks_by_album.get(album_id, [])


class StubSoulseekClient:
    def __init__(self) -> None:
        self.downloads: Dict[int, Dict[str, Any]] = {}

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


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    db_path = Path("test.db")
    if db_path.exists():
        db_path.unlink()
    yield


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> SimpleTestClient:
    stub_spotify = StubSpotifyClient()
    stub_plex = StubPlexClient()
    stub_soulseek = StubSoulseekClient()
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
    monkeypatch.setattr(deps, "get_matching_engine", lambda: engine)

    app.dependency_overrides[dependency_spotify_client] = lambda: stub_spotify
    app.dependency_overrides[dependency_plex_client] = lambda: stub_plex
    app.dependency_overrides[dependency_soulseek_client] = lambda: stub_soulseek
    app.dependency_overrides[dependency_matching_engine] = lambda: engine

    app.state.soulseek_stub = stub_soulseek
    app.state.plex_stub = stub_plex
    app.state.spotify_stub = stub_spotify
    app.state.sync_worker = SyncWorker(stub_soulseek)
    app.state.playlist_worker = PlaylistSyncWorker(stub_spotify, interval_seconds=0.1)

    with SimpleTestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
