"""Spotify domain service consolidating playlist, ingest and backfill logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Optional, Sequence, cast

from sqlalchemy.orm import Session

from app.config import AppConfig, SpotifyConfig
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
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
from app.utils.settings_store import write_setting
from app.dependencies import get_app_config
from app.workers.backfill_worker import BackfillWorker
from app.workers.sync_worker import SyncWorker


@dataclass(slots=True)
class PlaylistItemsResult:
    """Normalized representation of playlist items for API responses."""

    items: Sequence[dict[str, Any]]
    total: int


class SpotifyDomainService:
    """Aggregate Spotify use-cases across routers and workers."""

    def __init__(
        self,
        *,
        config: AppConfig,
        spotify_client: SpotifyClient,
        soulseek_client: SoulseekClient,
        app_state: Any,
        free_ingest_factory: Callable[[AppConfig, SoulseekClient, SyncWorker | None], FreeIngestService]
        | None = None,
        backfill_service_factory: Callable[[SpotifyConfig, SpotifyClient], BackfillService] | None = None,
        backfill_worker_factory: Callable[[BackfillService], BackfillWorker] | None = None,
    ) -> None:
        self._config = config
        self._spotify = spotify_client
        self._soulseek = soulseek_client
        self._state = app_state
        self._free_ingest_factory = free_ingest_factory or self._default_free_ingest_factory
        self._backfill_service_factory = backfill_service_factory or self._default_backfill_service_factory
        self._backfill_worker_factory = backfill_worker_factory or self._default_backfill_worker_factory

    # Factories ---------------------------------------------------------

    @staticmethod
    def _default_free_ingest_factory(
        config: AppConfig, soulseek: SoulseekClient, worker: SyncWorker | None
    ) -> FreeIngestService:
        return FreeIngestService(config=config, soulseek_client=soulseek, sync_worker=worker)

    @staticmethod
    def _default_backfill_service_factory(
        spotify_config: SpotifyConfig, spotify_client: SpotifyClient
    ) -> BackfillService:
        return BackfillService(spotify_config, spotify_client)

    @staticmethod
    def _default_backfill_worker_factory(service: BackfillService) -> BackfillWorker:
        return BackfillWorker(service)

    # Core Spotify operations ------------------------------------------

    def get_mode(self) -> Literal["FREE", "PRO"]:
        return self._config.spotify.mode

    def update_mode(self, mode: Literal["FREE", "PRO"]) -> None:
        write_setting("SPOTIFY_MODE", mode)
        get_app_config.cache_clear()

    def get_status(self) -> str:
        try:
            authenticated = self._spotify.is_authenticated()
        except Exception:  # pragma: no cover - defensive guard
            authenticated = False
        return "connected" if authenticated else "unauthenticated"

    def is_authenticated(self) -> bool:
        try:
            return bool(self._spotify.is_authenticated())
        except Exception:  # pragma: no cover - defensive guard
            return False

    def search_tracks(self, query: str) -> Sequence[dict[str, Any]]:
        response = self._spotify.search_tracks(query)
        return self._extract_items(response, "tracks")

    def search_artists(self, query: str) -> Sequence[dict[str, Any]]:
        response = self._spotify.search_artists(query)
        return self._extract_items(response, "artists")

    def search_albums(self, query: str) -> Sequence[dict[str, Any]]:
        response = self._spotify.search_albums(query)
        return self._extract_items(response, "albums")

    def get_followed_artists(self) -> Sequence[dict[str, Any]]:
        response = self._spotify.get_followed_artists()
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
        response = self._spotify.get_artist_releases(artist_id)
        raw_items = response.get("items") if isinstance(response, dict) else []
        if not isinstance(raw_items, Iterable):
            return []
        return [item for item in raw_items if isinstance(item, dict)]

    def get_artist_discography(self, artist_id: str) -> Sequence[dict[str, Any]]:
        response = self._spotify.get_artist_discography(artist_id)
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
        items = self._spotify.get_playlist_items(playlist_id, limit=limit)
        total = items.get("total")
        if total is None:
            total = items.get("tracks", {}).get("total") if isinstance(items, dict) else None
        if total is None:
            raw_items = items.get("items", []) if isinstance(items, dict) else []
            total = len(raw_items) if isinstance(raw_items, Iterable) else 0
        raw_items = items.get("items", []) if isinstance(items, dict) else []
        sequence: Sequence[dict[str, Any]] = [item for item in raw_items if isinstance(item, dict)]
        return PlaylistItemsResult(items=sequence, total=int(total or 0))

    def add_tracks_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> None:
        self._spotify.add_tracks_to_playlist(playlist_id, list(uris))

    def remove_tracks_from_playlist(self, playlist_id: str, uris: Sequence[str]) -> None:
        self._spotify.remove_tracks_from_playlist(playlist_id, list(uris))

    def reorder_playlist(self, playlist_id: str, *, range_start: int, insert_before: int) -> None:
        self._spotify.reorder_playlist_items(
            playlist_id,
            range_start=range_start,
            insert_before=insert_before,
        )

    def get_track_details(self, track_id: str) -> Optional[dict[str, Any]]:
        details = self._spotify.get_track_details(track_id)
        return details if details else None

    def get_audio_features(self, track_id: str) -> Optional[dict[str, Any]]:
        features = self._spotify.get_audio_features(track_id)
        return features if features else None

    def get_multiple_audio_features(self, track_ids: Sequence[str]) -> Sequence[dict[str, Any]]:
        response = self._spotify.get_multiple_audio_features(list(track_ids))
        audio_features = response.get("audio_features") if isinstance(response, dict) else []
        if not isinstance(audio_features, Iterable):
            return []
        return [item for item in audio_features if isinstance(item, dict)]

    def get_saved_tracks(self, *, limit: int) -> dict[str, Any]:
        saved = self._spotify.get_saved_tracks(limit=limit)
        items = saved.get("items", []) if isinstance(saved, dict) else []
        total = saved.get("total") if isinstance(saved, dict) else None
        if total is None and isinstance(items, Iterable):
            total = len(list(items))
        return {
            "items": [item for item in items if isinstance(item, dict)],
            "total": int(total or 0),
        }

    def save_tracks(self, track_ids: Sequence[str]) -> None:
        self._spotify.save_tracks(list(track_ids))

    def remove_saved_tracks(self, track_ids: Sequence[str]) -> None:
        self._spotify.remove_saved_tracks(list(track_ids))

    def get_current_user(self) -> Optional[dict[str, Any]]:
        profile = self._spotify.get_current_user()
        return profile if isinstance(profile, dict) else None

    def get_top_tracks(self, *, limit: int) -> Sequence[dict[str, Any]]:
        response = self._spotify.get_top_tracks(limit=limit)
        return self._extract_items(response, "items")

    def get_top_artists(self, *, limit: int) -> Sequence[dict[str, Any]]:
        response = self._spotify.get_top_artists(limit=limit)
        return self._extract_items(response, "items")

    def get_recommendations(
        self,
        *,
        seed_tracks: Optional[Sequence[str]] = None,
        seed_artists: Optional[Sequence[str]] = None,
        seed_genres: Optional[Sequence[str]] = None,
        limit: int,
    ) -> dict[str, Any]:
        response = self._spotify.get_recommendations(
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
        batch_hint: Optional[int] = None,
    ) -> IngestSubmission:
        service = self._build_free_ingest_service()
        return await service.submit(
            playlist_links=playlist_links,
            tracks=tracks,
            batch_hint=batch_hint,
        )

    def get_free_ingest_job(self, job_id: str) -> Optional[JobStatus]:
        service = self._build_free_ingest_service()
        return service.get_job_status(job_id)

    def parse_tracks_from_file(self, content: bytes, filename: str) -> Sequence[str]:
        return FreeIngestService.parse_tracks_from_file(content, filename)

    # Backfill ----------------------------------------------------------

    def ensure_backfill_service(self) -> BackfillService:
        service = getattr(self._state, "backfill_service", None)
        if isinstance(service, BackfillService):
            return service
        service = self._backfill_service_factory(self._config.spotify, self._spotify)
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
        self, *, max_items: Optional[int], expand_playlists: bool
    ) -> BackfillJobSpec:
        service = self.ensure_backfill_service()
        return service.create_job(max_items=max_items, expand_playlists=expand_playlists)

    def get_backfill_status(self, job_id: str) -> Optional[BackfillJobStatus]:
        service = self.ensure_backfill_service()
        return service.get_status(job_id)

    async def enqueue_backfill_job(self, job: BackfillJobSpec) -> None:
        worker = await self.ensure_backfill_worker()
        await worker.enqueue(job)

    # Helpers -----------------------------------------------------------

    def _build_free_ingest_service(self) -> FreeIngestService:
        sync_worker = getattr(self._state, "sync_worker", None)
        if not isinstance(sync_worker, SyncWorker):
            sync_worker = None
        return self._free_ingest_factory(self._config, self._soulseek, sync_worker)

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
