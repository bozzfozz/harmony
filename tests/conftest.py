from __future__ import annotations

# ruff: noqa: E402

pytest_plugins = [
    "tests.fixtures.async_client",
    "tests.fixtures.mocks_providers",
    "tests.fixtures.artists",
]

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("HARMONY_API_KEYS", "test-key")
os.environ.setdefault("ALLOWED_ORIGINS", "https://app.local")
os.environ.setdefault("CACHE_ENABLED", "true")
os.environ.setdefault("CACHE_DEFAULT_TTL_S", "30")
os.environ.setdefault("CACHE_MAX_ITEMS", "256")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/harmony"
)

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import NoSuchModuleError, OperationalError, ProgrammingError
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.transfers_api import TransfersApiError
from app.db import init_db, reset_engine_for_tests, session_scope
from app.dependencies import get_integration_service as dependency_integration_service
from app.dependencies import get_matching_engine as dependency_matching_engine
from app.dependencies import get_soulseek_client as dependency_soulseek_client
from app.dependencies import get_spotify_client as dependency_spotify_client
from app.dependencies import get_transfers_api as dependency_transfers_api
from app.integrations.base import TrackCandidate
from app.integrations.contracts import (
    ProviderAlbum,
    ProviderArtist,
    ProviderTrack,
    SearchQuery,
)
from app.integrations.health import IntegrationHealth, ProviderHealth
from app.integrations.provider_gateway import (
    ProviderGatewayInternalError,
    ProviderGatewaySearchResponse,
    ProviderGatewaySearchResult,
)
from app.logging import get_logger
from app.main import app
from app.models import ActivityEvent, QueueJobStatus
from app.orchestrator import bootstrap as orchestrator_bootstrap
from app.services.backfill_service import BackfillService
from app.utils.activity import activity_manager
from app.utils.settings_store import write_setting
from app.workers import persistence
from app.workers.artwork_worker import ArtworkWorker
from app.workers.lyrics_worker import LyricsWorker
from app.workers.metadata_worker import MetadataWorker
from app.workers.playlist_sync_worker import PlaylistSyncWorker
from app.workers.sync_worker import SyncWorker
from tests.simple_client import SimpleTestClient


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "lifespan_workers: enable worker lifecycle tests that re-enable background workers with test stubs.",
    )


class RecordingScheduler:
    """Test scheduler that records leased jobs without running a polling loop."""

    def __init__(
        self,
        *,
        job_types: Sequence[str] | None = None,
        persistence_module=persistence,
    ) -> None:
        self._persistence = persistence_module
        self._job_types = tuple(
            job_types
            or (
                "sync",
                "matching",
                "retry",
                "artist_refresh",
                "artist_scan",
                "artist_delta",
                "watchlist",
            )
        )
        self.poll_interval = 0.01
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.stop_requested = False
        self._stop_event: asyncio.Event | None = None
        self.leased_jobs: list[list[persistence.QueueJobDTO]] = []

    async def run(self, lifespan: asyncio.Event | None = None) -> None:
        self.started.set()
        self._stop_event = asyncio.Event()
        waiters = [asyncio.create_task(self._stop_event.wait())]
        if lifespan is not None:
            waiters.append(asyncio.create_task(lifespan.wait()))
        done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        self.stopped.set()

    def request_stop(self) -> None:
        self.stop_requested = True
        if self._stop_event is not None:
            self._stop_event.set()

    def lease_ready_jobs(self) -> list[persistence.QueueJobDTO]:
        ready: list[persistence.QueueJobDTO] = []
        for job_type in self._job_types:
            ready.extend(self._persistence.fetch_ready(job_type))
        ready.sort(
            key=lambda job: (-int(job.priority or 0), job.available_at, int(job.id))
        )
        leased: list[persistence.QueueJobDTO] = []
        for job in ready:
            record = self._persistence.lease(
                job.id,
                job_type=job.type,
                lease_seconds=job.lease_timeout_seconds,
            )
            if record is not None:
                leased.append(record)
        if leased:
            self.leased_jobs.append(leased)
        return leased


class RecordingDispatcher:
    """Thin wrapper around the real dispatcher with manual draining helpers."""

    def __init__(
        self, scheduler: RecordingScheduler, handlers: Mapping[str, Any]
    ) -> None:
        from app.orchestrator.dispatcher import Dispatcher as _Dispatcher

        self._impl = _Dispatcher(scheduler, handlers, persistence_module=persistence)
        self._stop_event: asyncio.Event | None = None
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.stop_requested = False
        self.processed_jobs: list[persistence.QueueJobDTO] = []

        # Expose selected internals for tests.
        self._handlers = self._impl._handlers
        self._scheduler = self._impl._scheduler
        self._persistence = self._impl._persistence

    async def run(self, lifespan: asyncio.Event | None = None) -> None:
        self.started.set()
        self._stop_event = asyncio.Event()
        waiters = [asyncio.create_task(self._stop_event.wait())]
        if lifespan is not None:
            waiters.append(asyncio.create_task(lifespan.wait()))
        done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        self.stop_requested = True
        self._impl.request_stop()
        self.stopped.set()

    def request_stop(self) -> None:
        self.stop_requested = True
        self._impl.request_stop()
        if self._stop_event is not None:
            self._stop_event.set()

    async def drain_once(self) -> list[persistence.QueueJobDTO]:
        leased = self._scheduler.lease_ready_jobs()
        processed: list[persistence.QueueJobDTO] = []
        for job in leased:
            handler = self._handlers.get(job.type)
            if handler is None:
                self._persistence.to_dlq(
                    job.id,
                    job_type=job.type,
                    reason="handler_missing",
                    payload=job.payload,
                )
                continue
            if job.type == "artist_sync":
                logging.getLogger("app").setLevel(logging.INFO)
                get_logger("app.orchestrator.handlers_artist").setLevel(logging.INFO)
            await self._impl._execute_job(job, handler)
            processed.append(job)
            self.processed_jobs.append(job)
        return processed

    def __getattr__(self, item: str) -> Any:
        return getattr(self._impl, item)


def _install_recording_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    original_bootstrap = orchestrator_bootstrap.bootstrap_orchestrator

    def build_test_orchestrator(
        *,
        metadata_service=None,
        artwork_service=None,
        lyrics_service=None,
    ) -> orchestrator_bootstrap.OrchestratorRuntime:
        logging.getLogger("app").setLevel(logging.INFO)
        logging.getLogger("app.orchestrator.handlers_artist").setLevel(logging.INFO)
        runtime = original_bootstrap(
            metadata_service=metadata_service,
            artwork_service=artwork_service,
            lyrics_service=lyrics_service,
        )
        if "artist_sync" in runtime.handlers:
            from app.orchestrator import providers as orchestrator_providers
            from app.orchestrator.artist_sync import build_artist_sync_handler

            deps = orchestrator_providers.build_artist_sync_handler_deps()
            runtime.handlers["artist_sync"] = build_artist_sync_handler(deps)
        enabled_job_types = [
            job_type
            for job_type, is_enabled in runtime.enabled_jobs.items()
            if is_enabled and isinstance(job_type, str)
        ]
        scheduler = RecordingScheduler(
            job_types=enabled_job_types or None,
            persistence_module=runtime.dispatcher._persistence,
        )
        dispatcher = RecordingDispatcher(scheduler, runtime.handlers)
        return orchestrator_bootstrap.OrchestratorRuntime(
            scheduler=scheduler,
            dispatcher=dispatcher,
            handlers=runtime.handlers,
            enabled_jobs=runtime.enabled_jobs,
            import_worker=runtime.import_worker,
        )

    monkeypatch.setattr(
        orchestrator_bootstrap,
        "bootstrap_orchestrator",
        build_test_orchestrator,
    )
    monkeypatch.setattr(
        "app.main.bootstrap_orchestrator", build_test_orchestrator, raising=False
    )


class StubQueuePersistence:
    """In-memory persistence stub for orchestrator specific tests."""

    def __init__(self) -> None:
        self.ready: dict[str, list[persistence.QueueJobDTO]] = {}
        self.leases: list[tuple[int, str, int]] = []
        self.heartbeats: list[tuple[int, str, int | None]] = []
        self.heartbeat_overrides: dict[int, list[bool]] = {}
        self.completed: list[int] = []
        self.failed: list[dict[str, Any]] = []
        self.dead_lettered: list[dict[str, Any]] = []

    def add_ready(self, job: persistence.QueueJobDTO) -> None:
        self.ready.setdefault(job.type, []).append(job)

    def fetch_ready(self, job_type: str) -> list[persistence.QueueJobDTO]:
        return list(self.ready.get(job_type, []))

    def lease(
        self,
        job_id: int,
        *,
        job_type: str,
        lease_seconds: int,
    ) -> persistence.QueueJobDTO | None:
        self.leases.append((job_id, job_type, lease_seconds))
        queue = self.ready.get(job_type)
        if not queue:
            return None
        for index, job in enumerate(queue):
            if job.id == job_id:
                queue.pop(index)
                return job
        return None

    def heartbeat(
        self,
        job_id: int,
        *,
        job_type: str,
        lease_seconds: int | None = None,
    ) -> bool:
        outcomes = self.heartbeat_overrides.get(job_id)
        if outcomes:
            result = outcomes.pop(0)
        else:
            result = True
        self.heartbeats.append((job_id, job_type, lease_seconds))
        return result

    def complete(
        self,
        job_id: int,
        *,
        job_type: str,
        result_payload: Mapping[str, Any] | None = None,
    ) -> bool:
        self.completed.append(job_id)
        return True

    def fail(
        self,
        job_id: int,
        *,
        job_type: str,
        error: str | None = None,
        retry_in: int | None = None,
        available_at: datetime | None = None,
    ) -> bool:
        self.failed.append(
            {
                "job_id": job_id,
                "job_type": job_type,
                "error": error,
                "retry_in": retry_in,
                "available_at": available_at,
            }
        )
        return True

    def to_dlq(
        self,
        job_id: int,
        *,
        job_type: str,
        reason: str,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        self.dead_lettered.append(
            {
                "job_id": job_id,
                "job_type": job_type,
                "reason": reason,
                "payload": dict(payload or {}),
            }
        )
        return True


@pytest.fixture
def queue_job_factory() -> Callable[..., persistence.QueueJobDTO]:
    def _factory(
        *,
        job_id: int,
        job_type: str,
        priority: int = 0,
        attempts: int = 0,
        available_at: datetime | None = None,
        lease_timeout_seconds: int = 60,
    ) -> persistence.QueueJobDTO:
        return persistence.QueueJobDTO(
            id=job_id,
            type=job_type,
            payload={},
            priority=priority,
            attempts=attempts,
            available_at=available_at or datetime.utcnow(),
            lease_expires_at=None,
            status=QueueJobStatus.PENDING,
            idempotency_key=None,
            lease_timeout_seconds=lease_timeout_seconds,
        )

    return _factory


@pytest.fixture
def stub_queue_persistence() -> StubQueuePersistence:
    return StubQueuePersistence()


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
        self.followed_artists: List[Dict[str, Any]] = [
            {"id": "artist-1", "name": "Tester"}
        ]
        self.artist_releases: Dict[str, List[Dict[str, Any]]] = {
            "artist-1": [
                {"id": "release-1", "name": "Test Release", "album_group": "album"}
            ]
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
        return {
            "artists": {
                "items": [{"id": "artist-1", "name": "Tester", "genres": ["rock"]}]
            }
        }

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
        return {
            "artists": {"items": [dict(item) for item in self.followed_artists[:limit]]}
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
            "audio_features": [
                self.audio_features.get(track_id, {"id": track_id})
                for track_id in track_ids
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

    def add_tracks_to_playlist(
        self, playlist_id: str, track_uris: list[str]
    ) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(
            playlist_id, {"items": [], "total": 0}
        )
        for uri in track_uris:
            playlist["items"].append({"track": {"uri": uri}})
        playlist["total"] = len(playlist["items"])
        return {"snapshot_id": "mock"}

    def remove_tracks_from_playlist(
        self, playlist_id: str, track_uris: list[str]
    ) -> Dict[str, Any]:
        playlist = self.playlist_items.setdefault(
            playlist_id, {"items": [], "total": 0}
        )
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
        playlist = self.playlist_items.setdefault(
            playlist_id, {"items": [], "total": 0}
        )
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
        self._next_download_id = 1
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
                title = str(
                    file_info.get("title") or file_info.get("filename") or ""
                ).lower()
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
                        "artists": (
                            [file_info.get("artist")] if file_info.get("artist") else []
                        ),
                        "album": file_info.get("album"),
                        "year": file_info.get("year"),
                        "duration_ms": file_info.get("duration_ms"),
                        "bitrate": file_info.get("bitrate"),
                        "format": file_info.get("format"),
                        "genres": (
                            [file_info.get("genre")] if file_info.get("genre") else []
                        ),
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


async def _soulseek_get_download(
    self: StubSoulseekClient, download_id: str
) -> Dict[str, Any]:
    identifier = int(download_id)
    return self.downloads.get(identifier, {"id": identifier, "state": "unknown"})


async def _soulseek_get_all_downloads(
    self: StubSoulseekClient,
) -> list[Dict[str, Any]]:
    return list(self.downloads.values())


async def _soulseek_remove_completed_downloads(
    self: StubSoulseekClient,
) -> Dict[str, Any]:
    before = len(self.downloads)
    self.downloads = {
        k: v for k, v in self.downloads.items() if v.get("state") != "completed"
    }
    removed = before - len(self.downloads)
    return {"removed": removed}


async def _soulseek_get_queue_position(
    self: StubSoulseekClient, download_id: str
) -> Dict[str, Any]:
    identifier = int(download_id)
    return self.queue_positions.get(identifier, {"position": None})


async def _soulseek_enqueue(
    self: StubSoulseekClient, username: str, files: list[Dict[str, Any]]
) -> Dict[str, Any]:
    job_files: list[Dict[str, Any]] = []
    for file_info in files:
        entry = dict(file_info)
        if "download_id" not in entry:
            entry["download_id"] = self._next_download_id
            self._next_download_id += 1
        identifier = int(entry.get("download_id", 0))
        if identifier <= 0:
            continue
        self.downloads.setdefault(
            identifier,
            {
                "id": identifier,
                "filename": entry.get("filename", "unknown"),
                "progress": 0.0,
                "state": "queued",
            },
        )
        job_files.append(entry)
    job = {"username": username, "files": job_files}
    if job_files:
        job["id"] = job_files[0]["download_id"]
    self.enqueued.append(job)
    return {"status": "enqueued", "job": job}


async def _soulseek_cancel_upload(
    self: StubSoulseekClient, upload_id: str
) -> Dict[str, Any]:
    upload = self.uploads.get(upload_id)
    if upload:
        upload["state"] = "cancelled"
    return {"cancelled": upload_id}


async def _soulseek_get_upload(
    self: StubSoulseekClient, upload_id: str
) -> Dict[str, Any]:
    return self.uploads.get(upload_id, {"id": upload_id, "state": "unknown"})


async def _soulseek_get_uploads(self: StubSoulseekClient) -> list[Dict[str, Any]]:
    return [
        upload for upload in self.uploads.values() if upload.get("state") != "completed"
    ]


async def _soulseek_get_all_uploads(self: StubSoulseekClient) -> list[Dict[str, Any]]:
    return list(self.uploads.values())


async def _soulseek_remove_completed_uploads(
    self: StubSoulseekClient,
) -> Dict[str, Any]:
    before = len(self.uploads)
    self.uploads = {
        k: v for k, v in self.uploads.items() if v.get("state") != "completed"
    }
    removed = before - len(self.uploads)
    return {"removed": removed}


async def _soulseek_user_address(
    self: StubSoulseekClient, username: str
) -> Dict[str, Any]:
    record = self.user_records.get(username, {})
    return record.get("address", {"host": None, "port": None})


async def _soulseek_user_browse(
    self: StubSoulseekClient, username: str
) -> Dict[str, Any]:
    record = self.user_records.get(username, {})
    return record.get("browse", {"files": []})


async def _soulseek_user_browsing_status(
    self: StubSoulseekClient, username: str
) -> Dict[str, Any]:
    record = self.user_records.get(username, {})
    return record.get("browsing-status", {"state": "unknown"})


async def _soulseek_user_directory(
    self: StubSoulseekClient, username: str, path: str
) -> Dict[str, Any]:
    record = self.user_records.setdefault(username, {})
    directory = record.get("directory", {"path": path, "files": []})
    directory = dict(directory)
    directory["path"] = path
    return directory


async def _soulseek_user_info(
    self: StubSoulseekClient, username: str
) -> Dict[str, Any]:
    record = self.user_records.get(username, {})
    return record.get("info", {"username": username})


async def _soulseek_user_status(
    self: StubSoulseekClient, username: str
) -> Dict[str, Any]:
    record = self.user_records.get(username, {})
    return record.get("status", {"online": False})


def _soulseek_set_status(
    self: StubSoulseekClient,
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


StubSoulseekClient.get_download = _soulseek_get_download
StubSoulseekClient.get_all_downloads = _soulseek_get_all_downloads
StubSoulseekClient.remove_completed_downloads = _soulseek_remove_completed_downloads
StubSoulseekClient.get_queue_position = _soulseek_get_queue_position
StubSoulseekClient.enqueue = _soulseek_enqueue
StubSoulseekClient.cancel_upload = _soulseek_cancel_upload
StubSoulseekClient.get_upload = _soulseek_get_upload
StubSoulseekClient.get_uploads = _soulseek_get_uploads
StubSoulseekClient.get_all_uploads = _soulseek_get_all_uploads
StubSoulseekClient.remove_completed_uploads = _soulseek_remove_completed_uploads
StubSoulseekClient.user_address = _soulseek_user_address
StubSoulseekClient.user_browse = _soulseek_user_browse
StubSoulseekClient.user_browsing_status = _soulseek_user_browsing_status
StubSoulseekClient.user_directory = _soulseek_user_directory
StubSoulseekClient.user_info = _soulseek_user_info
StubSoulseekClient.user_status = _soulseek_user_status
StubSoulseekClient.set_status = _soulseek_set_status


class StubSearchGateway:
    def __init__(
        self, spotify: StubSpotifyClient, soulseek: StubSoulseekClient
    ) -> None:
        self._spotify = spotify
        self._soulseek = soulseek
        self.calls: list[tuple[tuple[str, ...], SearchQuery]] = []
        self.log_events: list[dict[str, Any]] = []

    async def search_many(
        self, providers: Sequence[str], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        self.calls.append((tuple(providers), query))
        results: list[ProviderGatewaySearchResult] = []
        gateway_logger = get_logger("app.integrations.provider_gateway")
        for provider in providers:
            normalized = provider.lower()
            if normalized == "spotify":
                tracks = self._spotify_tracks(query)
                results.append(
                    ProviderGatewaySearchResult(
                        provider="spotify", tracks=tuple(tracks)
                    )
                )
                event_payload = {
                    "event": "api.dependency",
                    "provider": "spotify",
                    "operation": "search_tracks",
                    "status": "success",
                    "attempt": 1,
                    "max_attempts": 1,
                    "duration_ms": 1,
                }
                gateway_logger.info("provider call", extra=event_payload)
                self.log_events.append(event_payload)
            elif normalized in {"slskd", "soulseek"}:
                tracks = self._soulseek_tracks(query)
                results.append(
                    ProviderGatewaySearchResult(provider="slskd", tracks=tuple(tracks))
                )
                event_payload = {
                    "event": "api.dependency",
                    "provider": "slskd",
                    "operation": "search_tracks",
                    "status": "success",
                    "attempt": 1,
                    "max_attempts": 1,
                    "duration_ms": 1,
                }
                gateway_logger.info("provider call", extra=event_payload)
                self.log_events.append(event_payload)
            else:
                error = ProviderGatewayInternalError(normalized, "provider not stubbed")
                results.append(
                    ProviderGatewaySearchResult(
                        provider=normalized, tracks=tuple(), error=error
                    )
                )
                event_payload = {
                    "event": "api.dependency",
                    "provider": normalized,
                    "operation": "search_tracks",
                    "status": "error",
                    "attempt": 1,
                    "max_attempts": 1,
                    "duration_ms": 1,
                    "error": error.__class__.__name__,
                }
                gateway_logger.warning("provider call", extra=event_payload)
                self.log_events.append(event_payload)
        return ProviderGatewaySearchResponse(results=tuple(results))

    def _spotify_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        payload = self._spotify.search_tracks(query.text, limit=query.limit)
        container = payload.get("tracks") if isinstance(payload, dict) else None
        items = container.get("items") if isinstance(container, dict) else []
        results: list[ProviderTrack] = []
        for raw in (items or [])[: query.limit]:
            if not isinstance(raw, dict):
                continue
            artists: list[ProviderArtist] = []
            for artist_payload in raw.get("artists") or []:
                if isinstance(artist_payload, dict):
                    artists.append(
                        ProviderArtist(
                            source="spotify",
                            source_id=str(artist_payload.get("id") or ""),
                            name=str(artist_payload.get("name") or ""),
                        )
                    )
            album_payload = (
                raw.get("album") if isinstance(raw.get("album"), dict) else None
            )
            album = None
            if isinstance(album_payload, dict):
                album_artists: list[ProviderArtist] = []
                for entry in album_payload.get("artists") or []:
                    if isinstance(entry, dict):
                        album_artists.append(
                            ProviderArtist(
                                source="spotify",
                                source_id=str(entry.get("id") or ""),
                                name=str(entry.get("name") or ""),
                            )
                        )
                album_metadata: dict[str, object] = {}
                release_date = album_payload.get("release_date")
                if release_date:
                    album_metadata["release_date"] = release_date
                album = ProviderAlbum(
                    name=str(album_payload.get("name") or ""),
                    id=str(album_payload.get("id") or ""),
                    artists=tuple(album_artists),
                    metadata=album_metadata,
                )
            track_metadata: dict[str, object] = {}
            track_id = raw.get("id")
            if track_id:
                track_metadata["id"] = track_id
            genre = raw.get("genre")
            if genre:
                track_metadata["genre"] = genre
            duration_ms = raw.get("duration_ms")
            external_ids = (
                raw.get("external_ids")
                if isinstance(raw.get("external_ids"), dict)
                else {}
            )
            isrc = external_ids.get("isrc") if isinstance(external_ids, dict) else None
            results.append(
                ProviderTrack(
                    name=str(raw.get("name") or ""),
                    provider="spotify",
                    artists=tuple(artists),
                    album=album,
                    duration_ms=duration_ms,
                    isrc=isrc,
                    candidates=(),
                    metadata=track_metadata,
                )
            )
        return results

    def _soulseek_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        tracks: list[ProviderTrack] = []
        limit = max(1, query.limit)
        count = 0
        for entry in self._soulseek.search_results:
            files = entry.get("files") or []
            username = entry.get("username")
            for file_info in files:
                if count >= limit:
                    return tracks
                if not isinstance(file_info, dict):
                    continue
                metadata: dict[str, Any] = {}
                identifier = file_info.get("id")
                if identifier:
                    metadata["id"] = identifier
                if file_info.get("genre"):
                    metadata["genre"] = file_info.get("genre")
                    metadata["genres"] = [file_info.get("genre")]
                if file_info.get("year") is not None:
                    metadata["year"] = file_info.get("year")
                if file_info.get("album"):
                    metadata["album"] = file_info.get("album")
                artist_name = file_info.get("artist")
                if artist_name:
                    metadata["artists"] = [artist_name]
                bitrate_value = self._coerce_int(file_info.get("bitrate"))
                size_value = self._coerce_int(
                    file_info.get("size")
                    or file_info.get("size_bytes")
                    or file_info.get("filesize")
                )
                seeders = self._coerce_int(file_info.get("seeders"))
                candidate = TrackCandidate(
                    title=str(
                        file_info.get("title") or file_info.get("filename") or ""
                    ),
                    artist=str(artist_name) if artist_name else None,
                    format=str(file_info.get("format") or "").upper() or None,
                    bitrate_kbps=bitrate_value,
                    size_bytes=size_value,
                    seeders=seeders,
                    username=str(username) if username else None,
                    availability=None,
                    source="slskd",
                    download_uri=file_info.get("filename"),
                    metadata=metadata,
                )
                provider_artists = (
                    (
                        ProviderArtist(
                            source="slskd",
                            source_id=str(artist_name),
                            name=str(artist_name),
                        ),
                    )
                    if artist_name
                    else ()
                )
                album = None
                if file_info.get("album"):
                    album = ProviderAlbum(
                        name=str(file_info.get("album")), id=None, artists=()
                    )
                tracks.append(
                    ProviderTrack(
                        name=candidate.title,
                        provider="slskd",
                        artists=provider_artists,
                        album=album,
                        duration_ms=None,
                        isrc=None,
                        candidates=(candidate,),
                        metadata={
                            "genre": file_info.get("genre"),
                            "genres": metadata.get("genres", []),
                            "year": file_info.get("year"),
                        },
                    )
                )
                count += 1
                if count >= limit:
                    return tracks
        return tracks

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if text.isdigit():
            try:
                return int(text)
            except ValueError:
                return None
        return None

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
        self.downloads = {
            k: v for k, v in self.downloads.items() if v.get("state") != "completed"
        }
        removed = before - len(self.downloads)
        return {"removed": removed}

    async def get_queue_position(self, download_id: str) -> Dict[str, Any]:
        identifier = int(download_id)
        return self.queue_positions.get(identifier, {"position": None})

    async def enqueue(
        self, username: str, files: list[Dict[str, Any]]
    ) -> Dict[str, Any]:
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
        return [
            upload
            for upload in self.uploads.values()
            if upload.get("state") != "completed"
        ]

    async def get_all_uploads(self) -> list[Dict[str, Any]]:
        return list(self.uploads.values())

    async def remove_completed_uploads(self) -> Dict[str, Any]:
        before = len(self.uploads)
        self.uploads = {
            k: v for k, v in self.uploads.items() if v.get("state") != "completed"
        }
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


class StubIntegrationService:
    def __init__(self, gateway: StubSearchGateway) -> None:
        self._gateway = gateway
        self._providers: tuple[str, ...] = ("spotify", "slskd")
        self.calls: list[tuple[tuple[str, ...], SearchQuery]] = []

    async def search_providers(
        self, providers: Sequence[str], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        self.calls.append((tuple(providers), query))
        return await self._gateway.search_many(providers, query)

    async def search_tracks(
        self,
        provider: str,
        query: str,
        *,
        artist: str | None = None,
        limit: int = 50,
    ) -> list[TrackCandidate]:
        query_model = SearchQuery(text=query, artist=artist, limit=limit)
        response = await self.search_providers((provider,), query_model)
        candidates: list[TrackCandidate] = []
        for result in response.results:
            for track in result.tracks:
                candidates.extend(track.candidates)
        return candidates

    def providers(self) -> Iterable[object]:  # pragma: no cover - simple stub
        return ()

    async def health(self) -> IntegrationHealth:  # pragma: no cover - simple stub
        providers = tuple(
            ProviderHealth(provider=name, status="ok", details={})
            for name in self._providers
        )
        return IntegrationHealth(overall="ok", providers=providers)


class StubTransfersApi:
    def __init__(self, soulseek: StubSoulseekClient) -> None:
        self._soulseek = soulseek
        self.cancelled: list[int] = []
        self.enqueued: list[Dict[str, Any]] = []
        self.raise_cancel: TransfersApiError | None = None
        self.raise_enqueue: TransfersApiError | None = None

    async def cancel_download(self, download_id: int | str) -> bool:
        if self.raise_cancel is not None:
            raise self.raise_cancel
        identifier = int(download_id)
        self.cancelled.append(identifier)
        await self._soulseek.cancel_download(str(identifier))
        return True

    async def enqueue(self, *, username: str, files: list[Dict[str, Any]]) -> str:
        if self.raise_enqueue is not None:
            raise self.raise_enqueue
        job = {"username": username, "files": files}
        self.enqueued.append(job)
        response = await self._soulseek.enqueue(username, files)
        job_payload = response.get("job") if isinstance(response, dict) else None
        if isinstance(job_payload, dict):
            identifier = job_payload.get("id") or job_payload.get("download_id")
            if identifier is not None:
                return str(identifier)
        if files:
            download_id = files[0].get("download_id")
            if download_id is not None:
                return str(download_id)
        return username


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
def configure_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory,
    request: pytest.FixtureRequest,
) -> None:
    from app import dependencies as deps

    deps.get_app_config.cache_clear()
    if hasattr(deps.get_spotify_client, "cache_clear"):
        deps.get_spotify_client.cache_clear()
    deps.get_soulseek_client.cache_clear()
    deps.get_transfers_api.cache_clear()
    deps.get_matching_engine.cache_clear()

    disable_workers = "1"
    if request.node.get_closest_marker("lifespan_workers") is not None:
        disable_workers = "0"
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", disable_workers)
    monkeypatch.setenv("ENABLE_ARTWORK", "1")
    monkeypatch.setenv("ENABLE_LYRICS", "1")
    _install_recording_orchestrator(monkeypatch)
    configured_url = os.getenv("DATABASE_URL")

    def _seed_settings() -> None:
        write_setting("SPOTIFY_CLIENT_ID", "stub-client")
        write_setting("SPOTIFY_CLIENT_SECRET", "stub-secret")
        write_setting("SPOTIFY_REDIRECT_URI", "http://localhost/callback")
        write_setting("SLSKD_URL", "http://localhost:5030")
        write_setting("SLSKD_API_KEY", "test-key")

    if not configured_url:
        pytest.skip(
            "DATABASE_URL must point to a PostgreSQL database for test execution"
        )

    try:
        resolved_url = make_url(configured_url)
    except Exception as exc:  # pragma: no cover - defensive parsing
        pytest.skip(f"DATABASE_URL is not a valid SQLAlchemy URL: {exc}")

    if resolved_url.get_backend_name() != "postgresql":
        pytest.skip(
            "DATABASE_URL must reference a PostgreSQL backend for this test suite"
        )

    schema_name = f"test_suite_{uuid.uuid4().hex}"
    try:
        base_engine = sa.create_engine(resolved_url)
    except (
        NoSuchModuleError,
        ImportError,
    ) as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL driver unavailable: {exc}")
    try:
        with base_engine.connect() as connection:
            connection.execute(CreateSchema(schema_name))
            connection.commit()
    except OperationalError as exc:  # pragma: no cover - environment guard
        base_engine.dispose()
        pytest.skip(
            "PostgreSQL database unavailable: start a local instance (for example "
            "with `docker compose up -d postgres`) or point DATABASE_URL to an "
            f"accessible server. (Original error: {exc})"
        )
    except Exception as exc:  # pragma: no cover - environment guard
        base_engine.dispose()
        pytest.skip(f"PostgreSQL database unavailable: {exc}")
    scoped_url = resolved_url.set(
        query={**resolved_url.query, "options": f"-csearch_path={schema_name}"}
    )
    monkeypatch.setenv("DATABASE_URL", str(scoped_url))
    reset_engine_for_tests()
    init_db()
    _seed_settings()
    try:
        yield
    finally:
        reset_engine_for_tests()
        with base_engine.connect() as connection:
            try:
                connection.execute(DropSchema(schema_name, cascade=True))
                connection.commit()
            except ProgrammingError:
                connection.rollback()
        base_engine.dispose()


@pytest.fixture(autouse=True)
def reset_activity_manager() -> None:
    activity_manager.clear()
    with session_scope() as session:
        session.query(ActivityEvent).delete()
    yield
    activity_manager.clear()
    with session_scope() as session:
        session.query(ActivityEvent).delete()


@pytest.fixture
def db_session():
    with session_scope() as session:
        yield session


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    artist_gateway_stub,
) -> SimpleTestClient:
    stub_spotify = StubSpotifyClient()
    stub_soulseek = StubSoulseekClient()
    stub_transfers = StubTransfersApi(stub_soulseek)
    stub_lyrics = StubLyricsWorker()
    engine = dependency_matching_engine()
    stub_gateway = StubSearchGateway(stub_spotify, stub_soulseek)
    stub_service = StubIntegrationService(stub_gateway)

    async def noop_async(self) -> None:  # type: ignore[override]
        return None

    monkeypatch.setattr(MetadataWorker, "start", noop_async)
    monkeypatch.setattr(MetadataWorker, "stop", noop_async)
    monkeypatch.setattr(ArtworkWorker, "start", noop_async)
    monkeypatch.setattr(ArtworkWorker, "stop", noop_async)
    monkeypatch.setattr(LyricsWorker, "start", noop_async)
    monkeypatch.setattr(LyricsWorker, "stop", noop_async)

    _install_recording_orchestrator(monkeypatch)

    async def enqueue_pending(self, job: Dict[str, Any]) -> None:  # type: ignore[override]
        persistence.enqueue(self._job_type, job)
        await stub_soulseek.download(job)

    monkeypatch.setattr(SyncWorker, "enqueue", enqueue_pending, raising=False)

    from app import dependencies as deps

    monkeypatch.setattr(deps, "get_spotify_client", lambda: stub_spotify)
    monkeypatch.setattr(deps, "get_soulseek_client", lambda: stub_soulseek)
    monkeypatch.setattr(deps, "get_transfers_api", lambda: stub_transfers)
    monkeypatch.setattr(deps, "get_matching_engine", lambda: engine)
    deps.set_integration_service_override(stub_service)

    with SimpleTestClient(app) as test_client:
        test_client.app.dependency_overrides[dependency_spotify_client] = (
            lambda: stub_spotify
        )
        test_client.app.dependency_overrides[dependency_soulseek_client] = (
            lambda: stub_soulseek
        )
        test_client.app.dependency_overrides[dependency_transfers_api] = (
            lambda: stub_transfers
        )
        test_client.app.dependency_overrides[dependency_matching_engine] = (
            lambda: engine
        )
        test_client.app.dependency_overrides[dependency_integration_service] = (
            lambda: stub_service
        )

        test_client.app.state.soulseek_stub = stub_soulseek
        test_client.app.state.transfers_stub = stub_transfers
        test_client.app.state.spotify_stub = stub_spotify
        test_client.app.state.lyrics_worker = stub_lyrics
        test_client.app.state.sync_worker = SyncWorker(
            stub_soulseek, lyrics_worker=stub_lyrics
        )
        test_client.app.state.playlist_worker = PlaylistSyncWorker(
            stub_spotify,
            interval_seconds=0.1,
            response_cache=getattr(test_client.app.state, "response_cache", None),
        )
        test_client.app.state.provider_gateway_stub = stub_gateway
        test_client.app.state.artist_gateway_stub = artist_gateway_stub
        test_client.app.state.integration_service_stub = stub_service
        yield test_client

    app.dependency_overrides.clear()
    app.state.provider_gateway_stub = None
    app.state.integration_service_stub = None
    deps.set_integration_service_override(None)


@pytest.fixture
def backfill_service(client: SimpleTestClient) -> BackfillService:
    from app import dependencies as deps

    config = deps.get_app_config()
    spotify_client = client.app.state.spotify_stub
    service = BackfillService(config.spotify, spotify_client)
    return service


@pytest.fixture
def lifespan_worker_settings(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    if request.node.get_closest_marker("lifespan_workers") is None:
        yield
        return
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "0")
    monkeypatch.setenv("HARMONY_TEST_FAKE_WORKERS", "1")
    yield
