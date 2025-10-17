"""Spotify domain service consolidating playlist, ingest and backfill logic."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

from sqlalchemy.orm import Session

from app.config import AppConfig, SpotifyConfig
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import SessionCallable
from app.errors import DependencyError
from app.integrations.contracts import ProviderTrack
from app.integrations.normalizers import normalize_spotify_track
from app.logging import get_logger
from app.logging_events import log_event
from app.models import Playlist
from app.services.backfill_service import (
    BackfillJobSpec,
    BackfillJobStatus,
    BackfillService,
)
from app.services.free_ingest_service import (
    FreeIngestService,
    IngestSubmission,
    JobStatus,
)
from app.workers.backfill_worker import BackfillWorker

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.workers.sync_worker import SyncWorker


logger = get_logger(__name__)


@dataclass(slots=True)
class PlaylistItemsResult:
    """Normalized representation of playlist items for API responses."""

    items: Sequence[ProviderTrack]
    total: int


@dataclass(slots=True)
class SpotifyServiceStatus:
    """Connection and availability details for Spotify integrations."""

    status: str
    free_available: bool
    pro_available: bool
    authenticated: bool


class SpotifyDomainService:
    """Aggregate Spotify use-cases across routers and workers."""

    def __init__(
        self,
        *,
        config: AppConfig,
        spotify_client: SpotifyClient | None,
        soulseek_client: SoulseekClient,
        app_state: Any,
        free_ingest_factory: (
            Callable[
                [
                    AppConfig,
                    SoulseekClient,
                    SyncWorker | None,
                    Callable[[SessionCallable[Any]], Awaitable[Any]] | None,
                ],
                FreeIngestService,
            ]
            | None
        ) = None,
        backfill_service_factory: (
            Callable[[SpotifyConfig, SpotifyClient | None], BackfillService] | None
        ) = None,
        backfill_worker_factory: (Callable[[BackfillService], BackfillWorker] | None) = None,
        session_runner: Callable[[SessionCallable[Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self._config = config
        self._spotify = spotify_client
        self._soulseek = soulseek_client
        self._state = app_state
        self._free_ingest_factory = free_ingest_factory or self._default_free_ingest_factory
        self._backfill_service_factory = (
            backfill_service_factory or self._default_backfill_service_factory
        )
        self._backfill_worker_factory = (
            backfill_worker_factory or self._default_backfill_worker_factory
        )
        self._session_runner = session_runner
        self._pro_available = self._credentials_configured()

    # Factories ---------------------------------------------------------

    @staticmethod
    def _default_free_ingest_factory(
        config: AppConfig,
        soulseek: SoulseekClient,
        worker: SyncWorker | None,
        session_runner: Callable[[SessionCallable[Any]], Awaitable[Any]] | None = None,
    ) -> FreeIngestService:
        return FreeIngestService(
            config=config,
            soulseek_client=soulseek,
            sync_worker=worker,
            session_runner=session_runner,
        )

    @staticmethod
    def _default_backfill_service_factory(
        spotify_config: SpotifyConfig, spotify_client: SpotifyClient | None
    ) -> BackfillService:
        return BackfillService(spotify_config, spotify_client)

    @staticmethod
    def _default_backfill_worker_factory(service: BackfillService) -> BackfillWorker:
        return BackfillWorker(service)

    # Core Spotify operations ------------------------------------------

    def get_status(self) -> SpotifyServiceStatus:
        pro_usable = self._pro_available and self._spotify is not None
        if not pro_usable:
            return SpotifyServiceStatus(
                status="unconfigured",
                free_available=True,
                pro_available=False,
                authenticated=False,
            )

        try:
            authenticated = bool(self._spotify.is_authenticated())
        except Exception:  # pragma: no cover - defensive guard
            authenticated = False

        status_value = "connected" if authenticated else "unauthenticated"
        return SpotifyServiceStatus(
            status=status_value,
            free_available=True,
            pro_available=True,
            authenticated=authenticated,
        )

    def is_authenticated(self) -> bool:
        if not self._pro_available or self._spotify is None:
            return False
        try:
            return bool(self._spotify.is_authenticated())
        except Exception:  # pragma: no cover - defensive guard
            return False

    def search_tracks(self, query: str) -> Sequence[ProviderTrack]:
        client = self._require_spotify()
        response = client.search_tracks(query)
        tracks_section = response.get("tracks") if isinstance(response, Mapping) else None
        raw_items = tracks_section.get("items") if isinstance(tracks_section, Mapping) else None
        normalized: list[ProviderTrack] = []
        if isinstance(raw_items, Iterable):
            for entry in raw_items:
                if isinstance(entry, Mapping):
                    normalized.append(normalize_spotify_track(entry, provider="spotify"))
        return tuple(normalized)

    def search_artists(self, query: str) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.search_artists(query)
        return self._extract_items(response, "artists")

    def search_albums(self, query: str) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.search_albums(query)
        return self._extract_items(response, "albums")

    def get_followed_artists(self) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.get_followed_artists()
        artists_section = response.get("artists") if isinstance(response, dict) else None
        items: Sequence[dict[str, Any]] = []
        if isinstance(artists_section, dict):
            raw_items = artists_section.get("items") or []
            if isinstance(raw_items, Iterable):
                items = [item for item in raw_items if isinstance(item, dict)]
        if not items and isinstance(response, dict):
            raw_items = response.get("items") or []
            if isinstance(raw_items, Iterable):
                items = [item for item in raw_items if isinstance(item, dict)]
        return items

    def get_artist_releases(self, artist_id: str) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.get_artist_releases(artist_id)
        raw_items = response.get("items") if isinstance(response, dict) else []
        if not isinstance(raw_items, Iterable):
            return []
        return [item for item in raw_items if isinstance(item, dict)]

    def get_artist_discography(self, artist_id: str) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.get_artist_discography(artist_id)
        albums_payload = response.get("albums") if isinstance(response, dict) else []
        albums: list[dict[str, Any]] = []
        for entry in albums_payload or []:
            if not isinstance(entry, dict):
                continue
            album_data = entry.get("album") if isinstance(entry.get("album"), dict) else None
            if album_data is None:
                album_data = {key: value for key, value in entry.items() if key != "tracks"}
            tracks_payload = entry.get("tracks")
            if isinstance(tracks_payload, list):
                track_items = [track for track in tracks_payload if isinstance(track, dict)]
            elif isinstance(tracks_payload, dict):
                raw_items = tracks_payload.get("items") if isinstance(tracks_payload, dict) else []
                track_items = [track for track in raw_items if isinstance(track, dict)]
            else:
                track_items = []
            albums.append({"album": album_data, "tracks": track_items})
        return albums

    def list_playlists(self, session: Session) -> Sequence[Playlist]:
        return session.query(Playlist).order_by(Playlist.updated_at.desc()).all()

    def get_playlist_items(self, playlist_id: str, *, limit: int) -> PlaylistItemsResult:
        client = self._require_spotify()
        payload = client.get_playlist_items(playlist_id, limit=limit)
        total = payload.get("total") if isinstance(payload, Mapping) else None
        if total is None and isinstance(payload, Mapping):
            tracks_payload = payload.get("tracks")
            if isinstance(tracks_payload, Mapping):
                total = tracks_payload.get("total")

        raw_items = payload.get("items") if isinstance(payload, Mapping) else None
        iterable_items = raw_items if isinstance(raw_items, Iterable) else ()
        filtered_items: list[Mapping[str, Any]] = [
            entry for entry in iterable_items if isinstance(entry, Mapping)
        ]

        normalized_tracks: list[ProviderTrack] = []
        for entry in filtered_items:
            track_payload = entry.get("track")
            if not isinstance(track_payload, Mapping):
                continue
            track = normalize_spotify_track(track_payload, provider="spotify")
            metadata = dict(track.metadata or {})
            playlist_metadata: dict[str, Any] = {}

            added_at = entry.get("added_at")
            if isinstance(added_at, str) and added_at.strip():
                playlist_metadata["added_at"] = added_at

            is_local = entry.get("is_local")
            if isinstance(is_local, bool):
                playlist_metadata["is_local"] = is_local

            added_by = entry.get("added_by")
            added_by_mapping = added_by if isinstance(added_by, Mapping) else None
            if added_by_mapping:
                added_by_meta: dict[str, Any] = {}
                for key in ("id", "type", "uri"):
                    value = added_by_mapping.get(key)
                    if isinstance(value, str) and value.strip():
                        added_by_meta[key] = value
                display_name = added_by_mapping.get("display_name")
                if isinstance(display_name, str) and display_name.strip():
                    added_by_meta["display_name"] = display_name
                if added_by_meta:
                    playlist_metadata["added_by"] = added_by_meta

            if playlist_metadata:
                metadata["playlist_item"] = playlist_metadata

            normalized_tracks.append(replace(track, metadata=metadata))

        fallback_total = total if total is not None else len(filtered_items)
        return PlaylistItemsResult(items=tuple(normalized_tracks), total=int(fallback_total or 0))

    def add_tracks_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> None:
        client = self._require_spotify()
        client.add_tracks_to_playlist(playlist_id, list(uris))

    def remove_tracks_from_playlist(self, playlist_id: str, uris: Sequence[str]) -> None:
        client = self._require_spotify()
        client.remove_tracks_from_playlist(playlist_id, list(uris))

    def reorder_playlist(self, playlist_id: str, *, range_start: int, insert_before: int) -> None:
        client = self._require_spotify()
        client.reorder_playlist_items(
            playlist_id,
            range_start=range_start,
            insert_before=insert_before,
        )

    def get_track_details(self, track_id: str) -> dict[str, Any] | None:
        client = self._require_spotify()
        details = client.get_track_details(track_id)
        return details if details else None

    def get_audio_features(self, track_id: str) -> dict[str, Any] | None:
        client = self._require_spotify()
        features = client.get_audio_features(track_id)
        return features if features else None

    def get_multiple_audio_features(self, track_ids: Sequence[str]) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.get_multiple_audio_features(list(track_ids))
        audio_features = response.get("audio_features") if isinstance(response, dict) else []
        if not isinstance(audio_features, Iterable):
            return []
        return [item for item in audio_features if isinstance(item, dict)]

    def get_saved_tracks(self, *, limit: int, offset: int = 0) -> dict[str, Any]:
        client = self._require_spotify()
        saved = client.get_saved_tracks(limit=limit, offset=offset)
        items = saved.get("items", []) if isinstance(saved, dict) else []
        total = saved.get("total") if isinstance(saved, dict) else None
        if total is None and isinstance(items, Iterable):
            total = len(list(items))
        return {
            "items": [item for item in items if isinstance(item, dict)],
            "total": int(total or 0),
        }

    def save_tracks(self, track_ids: Sequence[str]) -> None:
        client = self._require_spotify()
        client.save_tracks(list(track_ids))

    def remove_saved_tracks(self, track_ids: Sequence[str]) -> None:
        client = self._require_spotify()
        client.remove_saved_tracks(list(track_ids))

    def get_current_user(self) -> dict[str, Any] | None:
        client = self._require_spotify()
        profile = client.get_current_user()
        return profile if isinstance(profile, dict) else None

    def get_top_tracks(self, *, limit: int) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.get_top_tracks(limit=limit)
        return self._extract_items(response, "items")

    def get_top_artists(self, *, limit: int) -> Sequence[dict[str, Any]]:
        client = self._require_spotify()
        response = client.get_top_artists(limit=limit)
        return self._extract_items(response, "items")

    def get_recommendations(
        self,
        *,
        seed_tracks: Sequence[str] | None = None,
        seed_artists: Sequence[str] | None = None,
        seed_genres: Sequence[str] | None = None,
        limit: int,
    ) -> dict[str, Any]:
        client = self._require_spotify()
        response = client.get_recommendations(
            seed_tracks=list(seed_tracks) if seed_tracks else None,
            seed_artists=list(seed_artists) if seed_artists else None,
            seed_genres=list(seed_genres) if seed_genres else None,
            limit=limit,
        )
        tracks = response.get("tracks") if isinstance(response, dict) else []
        seeds = response.get("seeds") if isinstance(response, dict) else []
        return {
            "tracks": [track for track in tracks if isinstance(track, dict)],
            "seeds": [seed for seed in seeds if isinstance(seed, dict)],
        }

    # FREE ingest -------------------------------------------------------

    async def submit_free_ingest(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> IngestSubmission:
        return await self._submit_free_import(
            playlist_links=playlist_links,
            tracks=tracks,
            batch_hint=batch_hint,
        )

    async def free_import(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> IngestSubmission:
        """Submit a FREE import request via the orchestrator."""

        from app.orchestrator import handlers as orchestrator_handlers

        started = perf_counter()
        result = await orchestrator_handlers.enqueue_spotify_free_import(
            self,
            playlist_links=playlist_links,
            tracks=tracks,
            batch_hint=batch_hint,
        )

        duration_ms = round((perf_counter() - started) * 1_000, 3)
        status_value = "ok" if result.ok else "error"
        log_event(
            logger,
            "spotify.free_import",
            component="service.spotify",
            status=status_value,
            duration_ms=duration_ms,
            job_id=result.job_id,
            accepted_playlists=result.accepted.playlists,
            accepted_tracks=result.accepted.tracks,
            skipped_playlists=result.skipped.playlists,
            skipped_tracks=result.skipped.tracks,
            error=result.error,
        )
        return result

    def get_free_ingest_job(self, job_id: str) -> JobStatus | None:
        service = self._build_free_ingest_service()
        return service.get_job_status(job_id)

    async def _submit_free_import(
        self,
        *,
        playlist_links: Sequence[str] | None,
        tracks: Sequence[str] | None,
        batch_hint: int | None,
    ) -> IngestSubmission:
        service = self._build_free_ingest_service()
        return await service.submit(
            playlist_links=playlist_links,
            tracks=tracks,
            batch_hint=batch_hint,
        )

    def parse_tracks_from_file(self, content: bytes, filename: str) -> Sequence[str]:
        return FreeIngestService.parse_tracks_from_file(content, filename)

    # Backfill ----------------------------------------------------------

    def ensure_backfill_service(self) -> BackfillService:
        spotify_client = self._require_spotify()
        service = getattr(self._state, "backfill_service", None)
        if isinstance(service, BackfillService):
            return service
        service = self._backfill_service_factory(self._config.spotify, spotify_client)
        setattr(self._state, "backfill_service", service)
        return service

    async def ensure_backfill_worker(self) -> BackfillWorker:
        worker = getattr(self._state, "backfill_worker", None)
        if self._is_backfill_worker(worker):
            typed_worker = cast(BackfillWorker, worker)
            if not typed_worker.is_running():
                await typed_worker.start()
            return typed_worker
        service = self.ensure_backfill_service()
        worker = self._backfill_worker_factory(service)
        setattr(self._state, "backfill_worker", worker)
        await worker.start()
        return worker

    def create_backfill_job(
        self, *, max_items: int | None, expand_playlists: bool
    ) -> BackfillJobSpec:
        service = self.ensure_backfill_service()
        return service.create_job(max_items=max_items, expand_playlists=expand_playlists)

    def get_backfill_status(self, job_id: str) -> BackfillJobStatus | None:
        service = self.ensure_backfill_service()
        return service.get_status(job_id)

    async def enqueue_backfill(self, job: BackfillJobSpec) -> None:
        worker = await self.ensure_backfill_worker()
        await worker.enqueue(job)

    # Helpers -----------------------------------------------------------

    def _build_free_ingest_service(self) -> FreeIngestService:
        from app.workers.sync_worker import (
            SyncWorker,  # Local import to avoid circular dependency
        )

        sync_worker = getattr(self._state, "sync_worker", None)
        if not isinstance(sync_worker, SyncWorker):
            sync_worker = None
        return self._free_ingest_factory(
            self._config,
            self._soulseek,
            sync_worker,
            self._session_runner,
        )

    def _credentials_configured(self) -> bool:
        spotify_config = self._config.spotify
        credentials = (
            spotify_config.client_id,
            spotify_config.client_secret,
            spotify_config.redirect_uri,
        )
        for value in credentials:
            if not isinstance(value, str) or not value.strip():
                return False
        return True

    def _require_spotify(self) -> SpotifyClient:
        if not self._pro_available or self._spotify is None:
            raise DependencyError(
                "Spotify credentials are not configured.",
                meta={"component": "spotify", "pro_available": False},
            )
        return self._spotify

    @staticmethod
    def _extract_items(response: Any, key: str) -> Sequence[dict[str, Any]]:
        if not isinstance(response, dict):
            return []
        if key == "items":
            items = response.get("items", [])
        else:
            payload = response.get(key, {})
            if isinstance(payload, dict):
                items = payload.get("items", [])
            else:
                items = payload
        if not isinstance(items, Iterable):
            return []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _is_backfill_worker(candidate: Any) -> bool:
        if isinstance(candidate, BackfillWorker):
            return True
        required = ("start", "enqueue", "is_running")
        return all(hasattr(candidate, attr) for attr in required)


__all__ = ["PlaylistItemsResult", "SpotifyDomainService"]
