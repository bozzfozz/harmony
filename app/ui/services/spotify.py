from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Final

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.dependencies import (
    SessionRunner,
    get_app_config,
    get_db,
    get_oauth_service,
    get_session_runner,
    get_soulseek_client,
    get_spotify_client,
)
from app.logging import get_logger
from app.errors import AppError
from app.services.free_ingest_service import (
    IngestAccepted,
    IngestSkipped,
    IngestSubmission,
    JobCounts,
    JobStatus,
    PlaylistValidationError,
)
from app.services.oauth_service import OAuthManualRequest, OAuthManualResponse, OAuthService
from app.services.spotify_domain_service import (
    BackfillJobStatus,
    SpotifyDomainService,
    SpotifyServiceStatus,
)
from app.utils.settings_store import delete_setting, read_setting, write_setting

logger = get_logger(__name__)

_SPOTIFY_TIME_RANGES: Final[frozenset[str]] = frozenset({"short_term", "medium_term", "long_term"})
_RECOMMENDATION_SEED_SETTINGS_KEY: Final[str] = "spotify.recommendations.seed_defaults"
_SPOTIFY_TOKEN_CACHE_KEY: Final[str] = "SPOTIFY_TOKEN_INFO"


def _normalise_time_range(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate in _SPOTIFY_TIME_RANGES:
        return candidate
    return None


@dataclass(slots=True)
class SpotifyStatus:
    status: str
    free_available: bool
    pro_available: bool
    authenticated: bool


@dataclass(slots=True)
class SpotifyOAuthHealth:
    manual_enabled: bool
    redirect_uri: str | None
    public_host_hint: str | None
    active_transactions: int
    ttl_seconds: int


@dataclass(slots=True)
class SpotifyManualResult:
    ok: bool
    message: str


@dataclass(slots=True)
class SpotifyAccountSummary:
    display_name: str
    email: str | None
    product: str | None
    followers: int
    country: str | None


@dataclass(slots=True)
class SpotifyPlaylistRow:
    identifier: str
    name: str
    track_count: int
    updated_at: datetime


@dataclass(slots=True)
class SpotifyPlaylistFilterOption:
    value: str
    label: str


@dataclass(slots=True)
class SpotifyPlaylistFilters:
    owners: tuple[SpotifyPlaylistFilterOption, ...]
    sync_statuses: tuple[SpotifyPlaylistFilterOption, ...]


@dataclass(slots=True)
class SpotifyPlaylistItemRow:
    identifier: str
    name: str
    artists: tuple[str, ...]
    album: str | None
    added_at: datetime | None
    added_by: str | None
    is_local: bool
    metadata: Mapping[str, Any]


@dataclass(slots=True)
class SpotifyArtistRow:
    identifier: str
    name: str
    followers: int
    popularity: int
    genres: tuple[str, ...]
    external_url: str | None = None


@dataclass(slots=True)
class SpotifySavedTrackRow:
    identifier: str
    name: str
    artists: tuple[str, ...]
    album: str | None
    added_at: datetime | None


@dataclass(slots=True)
class SpotifyTopTrackRow:
    identifier: str
    name: str
    artists: tuple[str, ...]
    album: str | None
    popularity: int
    duration_ms: int | None
    rank: int
    external_url: str | None = None


@dataclass(slots=True)
class SpotifyTopArtistRow:
    identifier: str
    name: str
    followers: int
    popularity: int
    genres: tuple[str, ...]
    rank: int
    external_url: str | None = None


@dataclass(slots=True)
class SpotifyRecommendationSeed:
    seed_type: str
    identifier: str
    initial_pool_size: int | None
    after_filtering_size: int | None
    after_relinking_size: int | None

    @property
    def size_summary(self) -> str:
        parts: list[str] = []
        if self.initial_pool_size is not None:
            parts.append(f"pool {self.initial_pool_size}")
        if self.after_filtering_size is not None:
            parts.append(f"filtered {self.after_filtering_size}")
        if self.after_relinking_size is not None:
            parts.append(f"relinked {self.after_relinking_size}")
        return " → ".join(parts)

    @property
    def has_size_summary(self) -> bool:
        return bool(self.size_summary)


@dataclass(slots=True)
class SpotifyRecommendationRow:
    identifier: str
    name: str
    artists: tuple[str, ...]
    album: str | None
    preview_url: str | None
    external_url: str | None = None


@dataclass(slots=True)
class SpotifyBackfillSnapshot:
    csrf_token: str
    can_run: bool
    default_max_items: int | None
    expand_playlists: bool
    options: tuple["SpotifyBackfillOption", ...]
    last_job_id: str | None
    state: str | None
    requested: int | None
    processed: int | None
    matched: int | None
    cache_hits: int | None
    cache_misses: int | None
    expanded_playlists: int | None
    expanded_tracks: int | None
    duration_ms: int | None
    error: str | None
    can_pause: bool
    can_resume: bool
    can_cancel: bool


@dataclass(slots=True)
class SpotifyBackfillOption:
    name: str
    label_key: str
    description_key: str | None
    checked: bool
    enabled: bool = True


@dataclass(slots=True)
class SpotifyTrackDetail:
    track_id: str
    name: str | None
    artists: tuple[str, ...]
    album: str | None
    release_date: str | None
    duration_ms: int | None
    popularity: int | None
    explicit: bool
    preview_url: str | None
    external_url: str | None
    detail: Mapping[str, Any] | None
    features: Mapping[str, Any] | None


@dataclass(slots=True)
class SpotifyFreeIngestAccepted:
    playlists: int
    tracks: int
    batches: int


@dataclass(slots=True)
class SpotifyFreeIngestSkipped:
    playlists: int
    tracks: int
    reason: str | None


@dataclass(slots=True)
class SpotifyFreeIngestResult:
    ok: bool
    job_id: str | None
    accepted: SpotifyFreeIngestAccepted
    skipped: SpotifyFreeIngestSkipped
    error: str | None


@dataclass(slots=True)
class SpotifyFreeIngestJobCounts:
    registered: int
    normalized: int
    queued: int
    completed: int
    failed: int


@dataclass(slots=True)
class SpotifyFreeIngestJobSnapshot:
    job_id: str
    state: str
    counts: SpotifyFreeIngestJobCounts
    accepted: SpotifyFreeIngestAccepted
    skipped: SpotifyFreeIngestSkipped
    queued_tracks: int
    failed_tracks: int
    skipped_tracks: int
    skip_reason: str | None
    error: str | None


class SpotifyUiService:
    def __init__(
        self,
        *,
        request: Request,
        config: AppConfig,
        spotify_service: SpotifyDomainService,
        oauth_service: OAuthService,
        db_session: Session,
    ) -> None:
        self._request = request
        self._config = config
        self._spotify = spotify_service
        self._oauth = oauth_service
        self._db = db_session
        self._free_ingest_result: SpotifyFreeIngestResult | None = None
        self._free_ingest_error: str | None = None

    def status(self) -> SpotifyStatus:
        payload: SpotifyServiceStatus = self._spotify.get_status()
        logger.debug(
            "spotify.ui.status",
            extra={
                "status": payload.status,
                "free": payload.free_available,
                "pro": payload.pro_available,
                "authenticated": payload.authenticated,
            },
        )
        return SpotifyStatus(
            status=payload.status,
            free_available=payload.free_available,
            pro_available=payload.pro_available,
            authenticated=payload.authenticated,
        )

    def oauth_health(self) -> SpotifyOAuthHealth:
        info = self._oauth.health()
        manual_enabled = bool(info.get("manual_enabled"))
        redirect_raw = info.get("redirect_uri")
        if manual_enabled and isinstance(redirect_raw, str):
            redirect_uri = redirect_raw
        else:
            redirect_uri = None
        public_host_hint = info.get("public_host_hint")
        if not isinstance(public_host_hint, str):
            public_host_hint = None
        active_transactions = info.get("active_transactions")
        ttl_seconds = info.get("ttl_seconds")
        return SpotifyOAuthHealth(
            manual_enabled=manual_enabled,
            redirect_uri=redirect_uri,
            public_host_hint=public_host_hint,
            active_transactions=int(active_transactions or 0),
            ttl_seconds=int(ttl_seconds or 0),
        )

    def list_playlists(
        self,
        *,
        owner: str | None = None,
        sync_status: str | None = None,
    ) -> Sequence[SpotifyPlaylistRow]:
        playlists = self._spotify.list_playlists(self._db)
        owner_filter = self._normalise_filter(owner)
        status_filter = self._normalise_filter(sync_status)
        rows = [
            SpotifyPlaylistRow(
                identifier=playlist.id,
                name=playlist.name,
                track_count=int(playlist.track_count or 0),
                updated_at=playlist.updated_at or datetime.utcnow(),
            )
            for playlist in playlists
            if self._matches_playlist_filters(
                playlist, owner_filter=owner_filter, status_filter=status_filter
            )
        ]
        logger.debug(
            "spotify.ui.playlists",
            extra={
                "count": len(rows),
                "owner_filter": owner_filter,
                "sync_status_filter": status_filter,
            },
        )
        return tuple(rows)

    def playlist_filters(self) -> SpotifyPlaylistFilters:
        playlists = self._spotify.list_playlists(self._db)
        owners: set[str] = set()
        statuses: set[str] = set()

        for playlist in playlists:
            owner_value = self._extract_owner(playlist)
            if owner_value:
                owners.add(owner_value)

            status_value = self._extract_sync_status(playlist)
            if status_value:
                statuses.add(status_value)

        owner_options = tuple(
            SpotifyPlaylistFilterOption(value=value, label=self._format_filter_label(value))
            for value in sorted(owners, key=str.lower)
        )
        status_options = tuple(
            SpotifyPlaylistFilterOption(value=value, label=self._format_filter_label(value))
            for value in sorted(statuses, key=str.lower)
        )

        logger.debug(
            "spotify.ui.playlists.filters",
            extra={
                "owner_count": len(owner_options),
                "status_count": len(status_options),
            },
        )
        return SpotifyPlaylistFilters(
            owners=owner_options,
            sync_statuses=status_options,
        )

    async def refresh_playlists(self) -> None:
        started = perf_counter()
        await self._spotify.refresh_playlists()
        duration_ms = round((perf_counter() - started) * 1_000, 3)
        logger.info("spotify.ui.playlists.refresh", extra={"duration_ms": duration_ms})

    async def force_sync_playlists(self) -> None:
        started = perf_counter()
        await self._spotify.force_sync_playlists()
        duration_ms = round((perf_counter() - started) * 1_000, 3)
        logger.info("spotify.ui.playlists.force_sync", extra={"duration_ms": duration_ms})

    def playlist_items(
        self,
        playlist_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[SpotifyPlaylistItemRow], int, int, int]:
        playlist_key = str(playlist_id or "").strip()
        if not playlist_key:
            raise ValueError("A Spotify playlist identifier is required.")

        page_limit = max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        result = self._spotify.get_playlist_items(
            playlist_key, limit=page_limit, offset=page_offset
        )

        rows: list[SpotifyPlaylistItemRow] = []
        items = getattr(result, "items", ())
        total_count = int(getattr(result, "total", 0) or 0)
        for entry in items:
            identifier = str(getattr(entry, "id", "") or "").strip()
            name = str(getattr(entry, "name", "") or "").strip()
            if not identifier or not name:
                continue

            artist_names: list[str] = []
            for artist in getattr(entry, "artists", ()):
                if isinstance(artist, Mapping):
                    artist_name_raw = artist.get("name")
                else:
                    artist_name_raw = getattr(artist, "name", artist)
                if isinstance(artist_name_raw, str):
                    artist_name = artist_name_raw.strip()
                    if artist_name:
                        artist_names.append(artist_name)

            album_name: str | None = None
            album = getattr(entry, "album", None)
            if isinstance(album, Mapping):
                album_name_raw = album.get("name")
            else:
                album_name_raw = getattr(album, "name", None)
            if isinstance(album_name_raw, str):
                album_candidate = album_name_raw.strip()
                if album_candidate:
                    album_name = album_candidate

            metadata_payload = getattr(entry, "metadata", {})
            metadata: dict[str, Any]
            if isinstance(metadata_payload, Mapping):
                metadata = dict(metadata_payload)
            else:
                metadata = {}

            playlist_meta_raw = metadata.get("playlist_item")
            playlist_meta_source = (
                playlist_meta_raw if isinstance(playlist_meta_raw, Mapping) else {}
            )

            playlist_metadata: dict[str, Any] = {}
            added_at_value = self._parse_timestamp(playlist_meta_source.get("added_at"))
            if added_at_value:
                playlist_metadata["added_at"] = added_at_value.isoformat()

            is_local_value = playlist_meta_source.get("is_local")
            is_local = bool(is_local_value) if isinstance(is_local_value, bool) else False
            if isinstance(is_local_value, bool):
                playlist_metadata["is_local"] = is_local_value

            added_by_value: str | None = None
            added_by_raw = playlist_meta_source.get("added_by")
            if isinstance(added_by_raw, Mapping):
                added_by: dict[str, Any] = {}
                for key in ("id", "type", "uri"):
                    value = added_by_raw.get(key)
                    if isinstance(value, str):
                        candidate = value.strip()
                        if candidate:
                            added_by[key] = candidate
                display_name = added_by_raw.get("display_name")
                if isinstance(display_name, str) and display_name.strip():
                    added_by["display_name"] = display_name.strip()
                    added_by_value = display_name.strip()
                else:
                    for key in ("id", "uri"):
                        candidate = added_by.get(key)
                        if isinstance(candidate, str) and candidate:
                            added_by_value = candidate
                            break
                if added_by:
                    playlist_metadata["added_by"] = added_by

            if playlist_metadata:
                metadata["playlist_item"] = playlist_metadata

            rows.append(
                SpotifyPlaylistItemRow(
                    identifier=identifier,
                    name=name,
                    artists=tuple(artist_names),
                    album=album_name,
                    added_at=added_at_value,
                    added_by=added_by_value,
                    is_local=is_local,
                    metadata=metadata,
                )
            )

        logger.debug(
            "spotify.ui.playlist_items",
            extra={
                "playlist_id": playlist_key,
                "count": len(rows),
                "limit": page_limit,
                "offset": page_offset,
                "total": total_count,
            },
        )
        return tuple(rows), total_count, page_limit, page_offset

    @staticmethod
    def _normalise_filter(value: str | None) -> str | None:
        if not value:
            return None
        candidate = value.strip()
        return candidate.lower() if candidate else None

    @staticmethod
    def _format_filter_label(value: str) -> str:
        cleaned = value.replace("_", " ").strip()
        return cleaned.title() if cleaned else value

    def _extract_owner(self, playlist: Any) -> str | None:
        for attribute in ("owner", "owner_name", "owner_display_name", "owner_id"):
            owner_value = getattr(playlist, attribute, None)
            if isinstance(owner_value, str):
                owner_candidate = owner_value.strip()
                if owner_candidate:
                    return owner_candidate

        metadata = getattr(playlist, "metadata", None)
        if isinstance(metadata, Mapping):
            owner_value = metadata.get("owner")
            if isinstance(owner_value, str) and owner_value.strip():
                return owner_value.strip()
        return None

    def _extract_sync_status(self, playlist: Any) -> str | None:
        for attribute in ("sync_status", "sync_state", "status"):
            status_value = getattr(playlist, attribute, None)
            if isinstance(status_value, str):
                status_candidate = status_value.strip()
                if status_candidate:
                    return status_candidate

        metadata = getattr(playlist, "metadata", None)
        if isinstance(metadata, Mapping):
            status_value = metadata.get("sync_status")
            if isinstance(status_value, str) and status_value.strip():
                return status_value.strip()
        return None

    def _matches_playlist_filters(
        self,
        playlist: Any,
        *,
        owner_filter: str | None,
        status_filter: str | None,
    ) -> bool:
        if owner_filter:
            owner = self._extract_owner(playlist)
            if not owner or owner.lower() != owner_filter:
                return False

        if status_filter:
            status = self._extract_sync_status(playlist)
            if not status or status.lower() != status_filter:
                return False

        return True

    def list_followed_artists(self) -> Sequence[SpotifyArtistRow]:
        raw_payload = self._spotify.get_followed_artists()
        entries: Sequence[Mapping[str, object]]
        if isinstance(raw_payload, Sequence):
            entries = [entry for entry in raw_payload if isinstance(entry, Mapping)]
        else:
            entries = []

        rows: list[SpotifyArtistRow] = []
        for entry in entries:
            identifier_raw = entry.get("id")
            name_raw = entry.get("name")
            identifier = str(identifier_raw or "").strip()
            name = str(name_raw or "").strip()
            if not identifier or not name:
                continue

            followers_payload: Any = entry.get("followers")
            if isinstance(followers_payload, Mapping):
                followers_value = followers_payload.get("total")
            else:
                followers_value = followers_payload
            try:
                followers = int(followers_value or 0)
            except (TypeError, ValueError):
                followers = 0

            popularity_raw = entry.get("popularity")
            try:
                popularity = int(popularity_raw or 0)
            except (TypeError, ValueError):
                popularity = 0

            genres_raw = entry.get("genres")
            genres_list: list[str] = []
            if isinstance(genres_raw, Sequence) and not isinstance(genres_raw, (str, bytes)):
                for genre in genres_raw:
                    if isinstance(genre, str):
                        cleaned = genre.strip()
                        if cleaned:
                            genres_list.append(cleaned)

            external_url = None
            external_payload = entry.get("external_urls")
            if isinstance(external_payload, Mapping):
                external_raw = external_payload.get("spotify")
                if isinstance(external_raw, str):
                    external_candidate = external_raw.strip()
                    external_url = external_candidate or None

            rows.append(
                SpotifyArtistRow(
                    identifier=identifier,
                    name=name,
                    followers=followers,
                    popularity=popularity,
                    genres=tuple(genres_list),
                    external_url=external_url,
                )
            )

        logger.debug("spotify.ui.artists", extra={"count": len(rows)})
        return tuple(rows)

    @staticmethod
    def _parse_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        candidate = cleaned.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None

    def list_saved_tracks(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[SpotifySavedTrackRow], int]:
        page_limit = max(1, min(int(limit), 50))
        page_offset = max(0, int(offset))
        payload = self._spotify.get_saved_tracks(limit=page_limit, offset=page_offset)
        items = payload.get("items") if isinstance(payload, Mapping) else []
        total_raw = payload.get("total") if isinstance(payload, Mapping) else None
        total_count = int(total_raw or 0)

        rows: list[SpotifySavedTrackRow] = []
        if isinstance(items, Sequence):
            for entry in items[:page_limit]:
                if not isinstance(entry, Mapping):
                    continue
                track_payload = (
                    entry.get("track") if isinstance(entry.get("track"), Mapping) else None
                )
                if not isinstance(track_payload, Mapping):
                    continue
                identifier_raw = track_payload.get("id")
                name_raw = track_payload.get("name")
                identifier = str(identifier_raw or "").strip()
                name = str(name_raw or "").strip()
                if not identifier or not name:
                    continue

                artists_payload = track_payload.get("artists")
                artist_names: list[str] = []
                if isinstance(artists_payload, Sequence):
                    for artist_entry in artists_payload:
                        if isinstance(artist_entry, Mapping):
                            artist_name_raw = artist_entry.get("name")
                        else:
                            artist_name_raw = artist_entry
                        if isinstance(artist_name_raw, str):
                            artist_name = artist_name_raw.strip()
                            if artist_name:
                                artist_names.append(artist_name)

                album_payload = track_payload.get("album")
                album: str | None = None
                if isinstance(album_payload, Mapping):
                    album_name_raw = album_payload.get("name")
                    if isinstance(album_name_raw, str):
                        album_candidate = album_name_raw.strip()
                        album = album_candidate or None

                added_at = self._parse_timestamp(entry.get("added_at"))

                rows.append(
                    SpotifySavedTrackRow(
                        identifier=identifier,
                        name=name,
                        artists=tuple(artist_names),
                        album=album,
                        added_at=added_at,
                    )
                )

        logger.debug(
            "spotify.ui.saved_tracks",
            extra={
                "count": len(rows),
                "limit": page_limit,
                "offset": page_offset,
                "total": total_count,
            },
        )
        return tuple(rows), total_count

    @staticmethod
    def _clean_track_ids(track_ids: Sequence[str]) -> tuple[str, ...]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for track_id in track_ids:
            value = str(track_id or "").strip()
            if not value or value in seen:
                continue
            cleaned.append(value)
            seen.add(value)
        return tuple(cleaned)

    @staticmethod
    def _format_ingest_track(track_payload: Mapping[str, Any]) -> str | None:
        name_raw = track_payload.get("name")
        name = str(name_raw or "").strip()

        artists_payload = track_payload.get("artists")
        artist_names: list[str] = []
        if isinstance(artists_payload, Sequence) and not isinstance(artists_payload, (str, bytes)):
            for artist_entry in artists_payload:
                if isinstance(artist_entry, Mapping):
                    artist_name_raw = artist_entry.get("name")
                else:
                    artist_name_raw = artist_entry
                if isinstance(artist_name_raw, str):
                    artist_candidate = artist_name_raw.strip()
                    if artist_candidate:
                        artist_names.append(artist_candidate)

        album_name: str | None = None
        album_payload = track_payload.get("album")
        if isinstance(album_payload, Mapping):
            album_raw = album_payload.get("name")
            if isinstance(album_raw, str):
                album_candidate = album_raw.strip()
                if album_candidate:
                    album_name = album_candidate

        if not name or not artist_names:
            return None

        artist_text = ", ".join(artist_names)
        line = f"{artist_text} - {name}"
        if album_name:
            line = f"{line} ({album_name})"
        return line

    def save_tracks(self, track_ids: Sequence[str]) -> int:
        cleaned = self._clean_track_ids(track_ids)
        if not cleaned:
            raise ValueError("At least one Spotify track identifier is required.")
        self._spotify.save_tracks(cleaned)
        logger.info("spotify.ui.saved_tracks.save", extra={"count": len(cleaned)})
        return len(cleaned)

    def remove_saved_tracks(self, track_ids: Sequence[str]) -> int:
        cleaned = self._clean_track_ids(track_ids)
        if not cleaned:
            raise ValueError("At least one Spotify track identifier is required.")
        self._spotify.remove_saved_tracks(cleaned)
        logger.info("spotify.ui.saved_tracks.remove", extra={"count": len(cleaned)})
        return len(cleaned)

    async def queue_saved_tracks(self, track_ids: Sequence[str]) -> SpotifyFreeIngestResult:
        return await self._queue_tracks(
            track_ids,
            log_namespace="spotify.ui.saved_tracks.queue",
        )

    @staticmethod
    def _clean_seed_values(values: Sequence[str]) -> tuple[str, ...]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            candidate = str(value or "").strip()
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            cleaned.append(candidate)
            seen.add(key)
        return tuple(cleaned)

    async def queue_recommendation_tracks(
        self, track_ids: Sequence[str]
    ) -> SpotifyFreeIngestResult:
        return await self._queue_tracks(
            track_ids,
            log_namespace="spotify.ui.recommendations.queue",
        )

    async def _queue_tracks(
        self,
        track_ids: Sequence[str],
        *,
        log_namespace: str,
    ) -> SpotifyFreeIngestResult:
        cleaned = self._clean_track_ids(track_ids)
        if not cleaned:
            raise ValueError("At least one Spotify track identifier is required.")

        ingest_lines: list[str] = []
        skipped: list[str] = []
        for track_id in cleaned:
            try:
                detail = self._spotify.get_track_details(track_id)
            except AppError:
                raise
            except Exception:
                logger.exception(
                    f"{log_namespace}.detail_error",
                    extra={"track_id": track_id},
                )
                skipped.append(track_id)
                continue

            if not isinstance(detail, Mapping):
                skipped.append(track_id)
                continue

            formatted = self._format_ingest_track(detail)
            if not formatted:
                skipped.append(track_id)
                continue
            ingest_lines.append(formatted)

        if not ingest_lines:
            logger.warning(
                f"{log_namespace}.no_ingest_lines",
                extra={"requested": len(cleaned)},
            )
            raise ValueError("Unable to queue downloads for the selected tracks.")

        try:
            submission = await self._spotify.submit_free_ingest(tracks=tuple(ingest_lines))
        except PlaylistValidationError as exc:
            logger.warning(
                f"{log_namespace}.validation_error",
                extra={"invalid": len(exc.invalid_links), "requested": len(cleaned)},
            )
            raise ValueError("Unable to queue downloads for the selected tracks.") from exc
        except AppError:
            raise
        except Exception:
            logger.exception(
                f"{log_namespace}.submit_error",
                extra={"requested": len(cleaned), "prepared": len(ingest_lines)},
            )
            raise

        result = self._map_ingest_submission(submission)
        logger.info(
            f"{log_namespace}.success",
            extra={
                "requested": len(cleaned),
                "queued": result.accepted.tracks,
                "skipped": len(skipped),
                "job_id": result.job_id,
            },
        )
        return result

    def get_recommendation_seed_defaults(self) -> Mapping[str, str]:
        seeds = self._load_recommendation_seed_defaults()
        return self._format_seed_defaults(*seeds)

    def save_recommendation_seed_defaults(
        self,
        *,
        seed_tracks: Sequence[str],
        seed_artists: Sequence[str],
        seed_genres: Sequence[str],
    ) -> Mapping[str, str]:
        cleaned_tracks = self._clean_seed_values(seed_tracks)
        cleaned_artists = self._clean_seed_values(seed_artists)
        cleaned_genres = self._clean_seed_values(seed_genres)
        payload = {
            "tracks": list(cleaned_tracks),
            "artists": list(cleaned_artists),
            "genres": list(cleaned_genres),
        }
        write_setting(
            _RECOMMENDATION_SEED_SETTINGS_KEY,
            json.dumps(payload, separators=(",", ":")),
        )
        logger.info(
            "spotify.ui.recommendations.defaults.save",
            extra={
                "tracks": len(cleaned_tracks),
                "artists": len(cleaned_artists),
                "genres": len(cleaned_genres),
            },
        )
        return self._format_seed_defaults(
            cleaned_tracks,
            cleaned_artists,
            cleaned_genres,
        )

    def _load_recommendation_seed_defaults(
        self,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        raw = read_setting(_RECOMMENDATION_SEED_SETTINGS_KEY)
        if not raw:
            return (), (), ()
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("spotify.ui.recommendations.defaults.invalid_store")
            return (), (), ()

        def _extract(key: str) -> tuple[str, ...]:
            value = data.get(key)
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                return ()
            return self._clean_seed_values(tuple(str(item) for item in value))

        return _extract("tracks"), _extract("artists"), _extract("genres")

    @staticmethod
    def _format_seed_defaults(
        tracks: Sequence[str],
        artists: Sequence[str],
        genres: Sequence[str],
    ) -> Mapping[str, str]:
        return {
            "seed_tracks": ", ".join(tracks),
            "seed_artists": ", ".join(artists),
            "seed_genres": ", ".join(genres),
        }

    @staticmethod
    def _normalise_recommendation_rows(entries: object) -> tuple[SpotifyRecommendationRow, ...]:
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            return ()
        rows: list[SpotifyRecommendationRow] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            identifier = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            if not identifier or not name:
                continue
            artists_payload = entry.get("artists")
            artist_names: list[str] = []
            if isinstance(artists_payload, Sequence) and not isinstance(
                artists_payload, (str, bytes)
            ):
                for artist_entry in artists_payload:
                    if isinstance(artist_entry, Mapping):
                        artist_name_raw = artist_entry.get("name")
                    else:
                        artist_name_raw = artist_entry
                    if isinstance(artist_name_raw, str):
                        artist_name = artist_name_raw.strip()
                        if artist_name:
                            artist_names.append(artist_name)
            album: str | None = None
            album_payload = entry.get("album")
            if isinstance(album_payload, Mapping):
                album_name_raw = album_payload.get("name")
                if isinstance(album_name_raw, str):
                    album_candidate = album_name_raw.strip()
                    album = album_candidate or None
            preview_raw = entry.get("preview_url")
            preview_url = None
            if isinstance(preview_raw, str):
                preview_candidate = preview_raw.strip()
                preview_url = preview_candidate or None
            external_url = None
            external_payload = entry.get("external_urls")
            if isinstance(external_payload, Mapping):
                external_raw = external_payload.get("spotify")
                if isinstance(external_raw, str):
                    external_candidate = external_raw.strip()
                    external_url = external_candidate or None
            rows.append(
                SpotifyRecommendationRow(
                    identifier=identifier,
                    name=name,
                    artists=tuple(artist_names),
                    album=album,
                    preview_url=preview_url,
                    external_url=external_url,
                )
            )
        return tuple(rows)

    @staticmethod
    def _normalise_recommendation_seeds(entries: object) -> tuple[SpotifyRecommendationSeed, ...]:
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            return ()
        seeds: list[SpotifyRecommendationSeed] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            seed_type = str(entry.get("type") or "").strip().lower()
            identifier = str(entry.get("id") or "").strip()
            if not seed_type or not identifier:
                continue

            def _coerce_int(value: object) -> int | None:
                if value in (None, ""):
                    return None
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            seeds.append(
                SpotifyRecommendationSeed(
                    seed_type=seed_type,
                    identifier=identifier,
                    initial_pool_size=_coerce_int(entry.get("initialPoolSize")),
                    after_filtering_size=_coerce_int(entry.get("afterFilteringSize")),
                    after_relinking_size=_coerce_int(entry.get("afterRelinkingSize")),
                )
            )
        return tuple(seeds)

    @staticmethod
    def _map_ingest_counts(
        accepted: IngestAccepted | IngestSkipped,
    ) -> tuple[int, int, int | None]:
        playlists = int(getattr(accepted, "playlists", 0) or 0)
        tracks = int(getattr(accepted, "tracks", 0) or 0)
        batches = getattr(accepted, "batches", None)
        try:
            batches_value = int(batches) if batches is not None else None
        except (TypeError, ValueError):
            batches_value = None
        return playlists, tracks, batches_value

    def _map_ingest_submission(self, submission: IngestSubmission) -> SpotifyFreeIngestResult:
        accepted_playlists, accepted_tracks, accepted_batches = self._map_ingest_counts(
            submission.accepted
        )
        skipped_playlists, skipped_tracks, _ = self._map_ingest_counts(submission.skipped)
        accepted = SpotifyFreeIngestAccepted(
            playlists=accepted_playlists,
            tracks=accepted_tracks,
            batches=accepted_batches or 0,
        )
        skipped = SpotifyFreeIngestSkipped(
            playlists=skipped_playlists,
            tracks=skipped_tracks,
            reason=submission.skipped.reason,
        )
        return SpotifyFreeIngestResult(
            ok=submission.ok,
            job_id=submission.job_id or None,
            accepted=accepted,
            skipped=skipped,
            error=submission.error,
        )

    def _map_job_status(self, status: JobStatus) -> SpotifyFreeIngestJobSnapshot:
        counts = self._map_job_counts(status.counts)
        accepted_playlists, accepted_tracks, accepted_batches = self._map_ingest_counts(
            status.accepted
        )
        skipped_playlists, skipped_tracks, _ = self._map_ingest_counts(status.skipped)
        accepted = SpotifyFreeIngestAccepted(
            playlists=accepted_playlists,
            tracks=accepted_tracks,
            batches=accepted_batches or 0,
        )
        skipped = SpotifyFreeIngestSkipped(
            playlists=skipped_playlists,
            tracks=skipped_tracks,
            reason=status.skip_reason,
        )
        return SpotifyFreeIngestJobSnapshot(
            job_id=status.id,
            state=status.state,
            counts=counts,
            accepted=accepted,
            skipped=skipped,
            queued_tracks=int(status.queued_tracks or 0),
            failed_tracks=int(status.failed_tracks or 0),
            skipped_tracks=int(status.skipped_tracks or 0),
            skip_reason=status.skip_reason,
            error=status.error,
        )

    @staticmethod
    def _map_job_counts(counts: JobCounts) -> SpotifyFreeIngestJobCounts:
        return SpotifyFreeIngestJobCounts(
            registered=int(counts.registered or 0),
            normalized=int(counts.normalized or 0),
            queued=int(counts.queued or 0),
            completed=int(counts.completed or 0),
            failed=int(counts.failed or 0),
        )

    def _build_ingest_error(
        self,
        message: str,
        *,
        skipped_playlists: int = 0,
        skipped_tracks: int = 0,
        reason: str | None = None,
    ) -> SpotifyFreeIngestResult:
        accepted = SpotifyFreeIngestAccepted(playlists=0, tracks=0, batches=0)
        skipped = SpotifyFreeIngestSkipped(
            playlists=skipped_playlists,
            tracks=skipped_tracks,
            reason=reason,
        )
        return SpotifyFreeIngestResult(
            ok=False,
            job_id=None,
            accepted=accepted,
            skipped=skipped,
            error=message,
        )

    def _remember_free_ingest_result(
        self, result: SpotifyFreeIngestResult, *, error_message: str | None = None
    ) -> SpotifyFreeIngestResult:
        self._free_ingest_result = result
        self._free_ingest_error = error_message or result.error
        return result

    def consume_free_ingest_feedback(self) -> tuple[SpotifyFreeIngestResult | None, str | None]:
        result = self._free_ingest_result
        error = self._free_ingest_error
        self._free_ingest_result = None
        self._free_ingest_error = None
        return result, error

    @staticmethod
    def _render_playlist_validation_error(exc: PlaylistValidationError) -> str:
        invalid_links = getattr(exc, "invalid_links", None)
        if not invalid_links:
            return "One or more playlist links could not be validated."
        parts: list[str] = []
        for item in invalid_links:
            url = (item.url or "").strip()
            reason = (item.reason or "invalid").lower()
            if url:
                parts.append(f"{url} ({reason})")
            else:
                parts.append(reason)
        joined = ", ".join(parts)
        if not joined:
            return "Invalid playlist links provided."
        return f"Invalid playlist links: {joined}"

    def recommendations(
        self,
        *,
        seed_tracks: Sequence[str] | None = None,
        seed_artists: Sequence[str] | None = None,
        seed_genres: Sequence[str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]]:
        page_limit = max(1, min(int(limit), 100))
        cleaned_tracks = self._clean_seed_values(seed_tracks or ())
        cleaned_artists = self._clean_seed_values(seed_artists or ())
        cleaned_genres = self._clean_seed_values(seed_genres or ())
        payload = self._spotify.get_recommendations(
            seed_tracks=cleaned_tracks or None,
            seed_artists=cleaned_artists or None,
            seed_genres=cleaned_genres or None,
            limit=page_limit,
        )

        rows = self._normalise_recommendation_rows(
            payload.get("tracks") if isinstance(payload, Mapping) else []
        )
        seeds = self._normalise_recommendation_seeds(
            payload.get("seeds") if isinstance(payload, Mapping) else []
        )

        logger.debug(
            "spotify.ui.recommendations",
            extra={
                "count": len(rows),
                "limit": page_limit,
                "seed_tracks": len(cleaned_tracks),
                "seed_artists": len(cleaned_artists),
                "seed_genres": len(cleaned_genres),
            },
        )
        return tuple(rows), tuple(seeds)

    def account(self) -> SpotifyAccountSummary | None:
        profile = self._spotify.get_current_user()
        if not isinstance(profile, Mapping):
            return None

        display_name_raw = profile.get("display_name")
        display_name = str(display_name_raw or "").strip()
        if not display_name:
            fallback_id = str(profile.get("id") or "").strip()
            display_name = fallback_id or "Spotify user"

        email_raw = profile.get("email")
        email_text = str(email_raw or "").strip()
        email = email_text or None

        product_raw = profile.get("product")
        product_text = str(product_raw or "").strip()
        product = product_text.replace("_", " ").title() if product_text else None

        followers_payload: Any = profile.get("followers")
        if isinstance(followers_payload, Mapping):
            followers_raw = followers_payload.get("total")
        else:
            followers_raw = followers_payload
        try:
            followers = int(followers_raw or 0)
        except (TypeError, ValueError):
            followers = 0

        country_raw = profile.get("country")
        country_text = str(country_raw or "").strip().upper()
        country = country_text or None

        return SpotifyAccountSummary(
            display_name=display_name,
            email=email,
            product=product,
            followers=followers,
            country=country,
        )

    def refresh_account(self) -> SpotifyAccountSummary | None:
        self._clear_cached_tokens()
        summary = self.account()
        logger.info(
            "spotify.ui.account.refresh",
            extra={"has_summary": summary is not None},
        )
        return summary

    def reset_scopes(self) -> SpotifyAccountSummary | None:
        self._clear_cached_tokens()
        self._oauth.reset_scopes()
        summary = self.account()
        logger.info(
            "spotify.ui.account.reset_scopes",
            extra={"has_summary": summary is not None},
        )
        return summary

    def _clear_cached_tokens(self) -> None:
        delete_setting(_SPOTIFY_TOKEN_CACHE_KEY)

    async def manual_complete(self, *, redirect_url: str) -> SpotifyManualResult:
        request_payload = OAuthManualRequest(redirect_url=redirect_url)
        client_ip = self._request.client.host if self._request.client else None
        try:
            manual_result: OAuthManualResponse = await self._oauth.manual(
                request=request_payload, client_ip=client_ip
            )
        except ValueError as exc:
            logger.warning(
                "spotify.ui.manual.error",
                extra={"error": str(exc)},
            )
            return SpotifyManualResult(ok=False, message=str(exc))
        except Exception:
            logger.exception("spotify.ui.manual.error")
            return SpotifyManualResult(ok=False, message="Manual completion failed.")

        return SpotifyManualResult(ok=manual_result.ok, message=manual_result.message or "")

    def start_oauth(self) -> str:
        response = self._oauth.start(self._request)
        logger.info(
            "spotify.ui.oauth.start",
            extra={"authorization_url": response.authorization_url},
        )
        return response.authorization_url

    async def submit_free_ingest(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> SpotifyFreeIngestResult:
        try:
            submission = await self._spotify.submit_free_ingest(
                playlist_links=playlist_links,
                tracks=tracks,
                batch_hint=batch_hint,
            )
        except PlaylistValidationError as exc:
            logger.warning(
                "spotify.ui.free_ingest.validation",
                extra={"invalid": len(exc.invalid_links)},
            )
            message = self._render_playlist_validation_error(exc)
            error_result = self._build_ingest_error(
                message,
                skipped_playlists=len(exc.invalid_links),
                reason="invalid",
            )
            return self._remember_free_ingest_result(error_result, error_message=message)
        except Exception:
            logger.exception("spotify.ui.free_ingest.submit_error")
            error_result = self._build_ingest_error("Failed to submit the ingest request.")
            return self._remember_free_ingest_result(error_result)
        mapped = self._map_ingest_submission(submission)
        return self._remember_free_ingest_result(mapped)

    async def free_import(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> SpotifyFreeIngestResult:
        try:
            submission = await self._spotify.free_import(
                playlist_links=playlist_links,
                tracks=tracks,
                batch_hint=batch_hint,
            )
        except PermissionError as exc:
            logger.warning("spotify.ui.free_ingest.denied", extra={"error": str(exc)})
            error_result = self._build_ingest_error(
                "Spotify authentication is required before running the import."
            )
            return self._remember_free_ingest_result(error_result)
        except PlaylistValidationError as exc:
            logger.warning(
                "spotify.ui.free_ingest.validation",
                extra={"invalid": len(exc.invalid_links)},
            )
            message = self._render_playlist_validation_error(exc)
            error_result = self._build_ingest_error(
                message,
                skipped_playlists=len(exc.invalid_links),
                reason="invalid",
            )
            return self._remember_free_ingest_result(error_result, error_message=message)
        except Exception:
            logger.exception("spotify.ui.free_ingest.enqueue_error")
            error_result = self._build_ingest_error("Failed to enqueue the ingest job.")
            return self._remember_free_ingest_result(error_result)
        logger.info(
            "spotify.ui.free_ingest.enqueued",
            extra={
                "job_id": submission.job_id,
                "accepted_playlists": submission.accepted.playlists,
                "accepted_tracks": submission.accepted.tracks,
            },
        )
        mapped = self._map_ingest_submission(submission)
        return self._remember_free_ingest_result(mapped)

    async def upload_free_ingest_file(
        self,
        *,
        filename: str,
        content: bytes,
    ) -> SpotifyFreeIngestResult:
        limit = max(1, int(self._config.spotify.free_import_max_file_bytes))
        if len(content) > limit:
            message = "The uploaded file exceeds the allowed size. Please submit a smaller file."
            self._free_ingest_error = message
            raise ValueError(message)
        if not content:
            message = "The uploaded file is empty."
            error_result = self._build_ingest_error(message, reason="empty")
            return self._remember_free_ingest_result(error_result, error_message=message)
        try:
            tracks = self._spotify.parse_tracks_from_file(content, filename)
        except ValueError as exc:
            message = str(exc) or "Failed to parse the uploaded file."
            self._free_ingest_error = message
            raise
        if not tracks:
            message = "No tracks were found in the uploaded file."
            error_result = self._build_ingest_error(message, reason="empty")
            return self._remember_free_ingest_result(error_result, error_message=message)
        return await self.free_import(tracks=tracks)

    def free_ingest_job_status(self, job_id: str | None) -> SpotifyFreeIngestJobSnapshot | None:
        if not job_id:
            return None
        try:
            status = self._spotify.get_free_ingest_job(job_id)
        except Exception:
            logger.exception("spotify.ui.free_ingest.status_error")
            return None
        if status is None:
            return None
        return self._map_job_status(status)

    async def run_backfill(self, *, max_items: int | None, expand_playlists: bool) -> str:
        if not self._spotify.is_authenticated():
            raise PermissionError("Spotify authentication required")
        job = self._spotify.create_backfill_job(
            max_items=max_items,
            expand_playlists=expand_playlists,
        )
        await self._spotify.enqueue_backfill(job)
        logger.info(
            "spotify.ui.backfill.run",
            extra={"job_id": job.id, "limit": job.limit, "expand": expand_playlists},
        )
        return job.id

    def top_tracks(
        self,
        *,
        limit: int = 20,
        time_range: str | None = None,
    ) -> Sequence[SpotifyTopTrackRow]:
        page_limit = max(1, min(int(limit), 50))
        resolved_time_range = _normalise_time_range(time_range)
        items = self._spotify.get_top_tracks(limit=page_limit, time_range=resolved_time_range)
        rows: list[SpotifyTopTrackRow] = []
        if isinstance(items, Sequence):
            for index, entry in enumerate(items, start=1):
                if not isinstance(entry, Mapping):
                    continue
                identifier_raw = entry.get("id")
                name_raw = entry.get("name")
                identifier = str(identifier_raw or "").strip()
                name = str(name_raw or "").strip()
                if not identifier or not name:
                    continue

                artists_payload = entry.get("artists")
                artist_names: list[str] = []
                if isinstance(artists_payload, Sequence):
                    for artist_entry in artists_payload:
                        if isinstance(artist_entry, Mapping):
                            artist_name_raw = artist_entry.get("name")
                        else:
                            artist_name_raw = artist_entry
                        if isinstance(artist_name_raw, str):
                            cleaned_name = artist_name_raw.strip()
                            if cleaned_name:
                                artist_names.append(cleaned_name)

                album_payload = entry.get("album")
                album: str | None = None
                if isinstance(album_payload, Mapping):
                    album_name_raw = album_payload.get("name")
                    if isinstance(album_name_raw, str):
                        album_candidate = album_name_raw.strip()
                        album = album_candidate or None

                popularity_raw = entry.get("popularity")
                try:
                    popularity = int(popularity_raw or 0)
                except (TypeError, ValueError):
                    popularity = 0

                duration_raw = entry.get("duration_ms")
                try:
                    duration_ms = int(duration_raw) if duration_raw is not None else None
                except (TypeError, ValueError):
                    duration_ms = None

                external_url: str | None = None
                external_payload = entry.get("external_urls")
                if isinstance(external_payload, Mapping):
                    external_raw = external_payload.get("spotify")
                    if isinstance(external_raw, str):
                        external_candidate = external_raw.strip()
                        external_url = external_candidate or None

                rows.append(
                    SpotifyTopTrackRow(
                        identifier=identifier,
                        name=name,
                        artists=tuple(artist_names),
                        album=album,
                        popularity=popularity,
                        duration_ms=duration_ms,
                        rank=index,
                        external_url=external_url,
                    )
                )

        logger.debug(
            "spotify.ui.top_tracks",
            extra={
                "count": len(rows),
                "limit": page_limit,
                "time_range": resolved_time_range or "default",
            },
        )
        return tuple(rows)

    def track_detail(self, track_id: str) -> SpotifyTrackDetail:
        track_key = str(track_id or "").strip()
        if not track_key:
            raise ValueError("A Spotify track identifier is required.")

        detail_payload = self._spotify.get_track_details(track_key)
        detail: Mapping[str, Any] | None
        if isinstance(detail_payload, Mapping):
            detail = dict(detail_payload)
        else:
            detail = None

        features_payload = self._spotify.get_audio_features(track_key)
        features: Mapping[str, Any] | None
        if isinstance(features_payload, Mapping):
            features = dict(features_payload)
        else:
            features = None

        name: str | None = None
        artists: list[str] = []
        album: str | None = None
        release_date: str | None = None
        duration_ms: int | None = None
        popularity: int | None = None
        explicit = False
        preview_url: str | None = None
        external_url: str | None = None

        if detail:
            name_raw = detail.get("name")
            if isinstance(name_raw, str):
                candidate = name_raw.strip()
                name = candidate or None

            artists_payload = detail.get("artists")
            if isinstance(artists_payload, Sequence):
                for artist_entry in artists_payload:
                    if isinstance(artist_entry, Mapping):
                        artist_name_raw = artist_entry.get("name")
                    else:
                        artist_name_raw = artist_entry
                    if isinstance(artist_name_raw, str):
                        artist_candidate = artist_name_raw.strip()
                        if artist_candidate:
                            artists.append(artist_candidate)

            album_payload = detail.get("album")
            if isinstance(album_payload, Mapping):
                album_name_raw = album_payload.get("name")
                if isinstance(album_name_raw, str):
                    album_candidate = album_name_raw.strip()
                    album = album_candidate or None
                release_raw = album_payload.get("release_date")
                if isinstance(release_raw, str):
                    release_candidate = release_raw.strip()
                    release_date = release_candidate or None

            duration_raw = detail.get("duration_ms")
            try:
                duration_value = int(duration_raw) if duration_raw is not None else None
            except (TypeError, ValueError):
                duration_value = None
            duration_ms = duration_value

            popularity_raw = detail.get("popularity")
            try:
                popularity_value = int(popularity_raw) if popularity_raw is not None else None
            except (TypeError, ValueError):
                popularity_value = None
            popularity = popularity_value

            explicit_value = detail.get("explicit")
            explicit = (
                bool(explicit_value) if isinstance(explicit_value, bool) else bool(explicit_value)
            )

            preview_raw = detail.get("preview_url")
            if isinstance(preview_raw, str):
                preview_candidate = preview_raw.strip()
                preview_url = preview_candidate or None

            external_payload = detail.get("external_urls")
            if isinstance(external_payload, Mapping):
                external_raw = external_payload.get("spotify")
                if isinstance(external_raw, str):
                    external_candidate = external_raw.strip()
                    external_url = external_candidate or None

        return SpotifyTrackDetail(
            track_id=track_key,
            name=name,
            artists=tuple(artists),
            album=album,
            release_date=release_date,
            duration_ms=duration_ms,
            popularity=popularity,
            explicit=explicit,
            preview_url=preview_url,
            external_url=external_url,
            detail=detail,
            features=features,
        )

    def top_artists(
        self,
        *,
        limit: int = 20,
        time_range: str | None = None,
    ) -> Sequence[SpotifyTopArtistRow]:
        page_limit = max(1, min(int(limit), 50))
        resolved_time_range = _normalise_time_range(time_range)
        items = self._spotify.get_top_artists(limit=page_limit, time_range=resolved_time_range)
        rows: list[SpotifyTopArtistRow] = []
        if isinstance(items, Sequence):
            for index, entry in enumerate(items, start=1):
                if not isinstance(entry, Mapping):
                    continue
                identifier_raw = entry.get("id")
                name_raw = entry.get("name")
                identifier = str(identifier_raw or "").strip()
                name = str(name_raw or "").strip()
                if not identifier or not name:
                    continue

                followers_payload: Any = entry.get("followers")
                if isinstance(followers_payload, Mapping):
                    followers_raw = followers_payload.get("total")
                else:
                    followers_raw = followers_payload
                try:
                    followers = int(followers_raw or 0)
                except (TypeError, ValueError):
                    followers = 0

                popularity_raw = entry.get("popularity")
                try:
                    popularity = int(popularity_raw or 0)
                except (TypeError, ValueError):
                    popularity = 0

                genres_raw = entry.get("genres")
                genres: list[str] = []
                if isinstance(genres_raw, Sequence) and not isinstance(genres_raw, (str, bytes)):
                    for genre in genres_raw:
                        if isinstance(genre, str):
                            cleaned = genre.strip()
                            if cleaned:
                                genres.append(cleaned)

                external_url = None
                external_payload = entry.get("external_urls")
                if isinstance(external_payload, Mapping):
                    external_raw = external_payload.get("spotify")
                    if isinstance(external_raw, str):
                        external_candidate = external_raw.strip()
                        external_url = external_candidate or None

                rows.append(
                    SpotifyTopArtistRow(
                        identifier=identifier,
                        name=name,
                        followers=followers,
                        popularity=popularity,
                        genres=tuple(genres),
                        rank=index,
                        external_url=external_url,
                    )
                )

        logger.debug(
            "spotify.ui.top_artists",
            extra={
                "count": len(rows),
                "limit": page_limit,
                "time_range": resolved_time_range or "default",
            },
        )
        return tuple(rows)

    def backfill_status(self, job_id: str | None) -> Mapping[str, object] | None:
        if not job_id:
            return None
        status = self._spotify.get_backfill_status(job_id)
        return self._serialise_backfill_status(status)

    def pause_backfill(self, job_id: str) -> Mapping[str, object]:
        if not self._spotify.is_authenticated():
            raise PermissionError("Spotify authentication required")
        status = self._spotify.pause_backfill(job_id)
        logger.info(
            "spotify.ui.backfill.pause",
            extra={"job_id": job_id, "state": getattr(status, "state", None)},
        )
        payload = self._serialise_backfill_status(status)
        if payload is None:
            raise LookupError(job_id)
        return payload

    def resume_backfill(self, job_id: str) -> Mapping[str, object]:
        if not self._spotify.is_authenticated():
            raise PermissionError("Spotify authentication required")
        status = self._spotify.resume_backfill(job_id)
        logger.info(
            "spotify.ui.backfill.resume",
            extra={"job_id": job_id, "state": getattr(status, "state", None)},
        )
        payload = self._serialise_backfill_status(status)
        if payload is None:
            raise LookupError(job_id)
        return payload

    def cancel_backfill(self, job_id: str) -> Mapping[str, object]:
        if not self._spotify.is_authenticated():
            raise PermissionError("Spotify authentication required")
        status = self._spotify.cancel_backfill(job_id)
        logger.info(
            "spotify.ui.backfill.cancel",
            extra={"job_id": job_id, "state": getattr(status, "state", None)},
        )
        payload = self._serialise_backfill_status(status)
        if payload is None:
            raise LookupError(job_id)
        return payload

    def build_backfill_snapshot(
        self,
        *,
        csrf_token: str,
        job_id: str | None,
        status_payload: Mapping[str, object] | None,
    ) -> SpotifyBackfillSnapshot:
        raw_default = getattr(self._config.spotify, "backfill_max_items", None)
        default_max = int(raw_default) if raw_default else None
        expand = bool(status_payload.get("expand_playlists")) if status_payload else True
        requested = int(status_payload.get("requested", 0)) if status_payload else None
        processed = int(status_payload.get("processed", 0)) if status_payload else None
        matched = int(status_payload.get("matched", 0)) if status_payload else None
        cache_hits = int(status_payload.get("cache_hits", 0)) if status_payload else None
        cache_misses = int(status_payload.get("cache_misses", 0)) if status_payload else None
        expanded_playlists = (
            int(status_payload.get("expanded_playlists", 0)) if status_payload else None
        )
        expanded_tracks = int(status_payload.get("expanded_tracks", 0)) if status_payload else None
        duration_ms = int(status_payload.get("duration_ms", 0)) if status_payload else None
        state = status_payload.get("state") if status_payload else None
        options = (
            SpotifyBackfillOption(
                name="expand_playlists",
                label_key="spotify.backfill.options.expand_playlists",
                description_key="spotify.backfill.options.expand_playlists_hint",
                checked=expand,
            ),
            SpotifyBackfillOption(
                name="include_cached_results",
                label_key="spotify.backfill.options.include_cached",
                description_key="spotify.backfill.options.include_cached_hint",
                checked=True,
            ),
        )
        can_pause = state in {"running", "queued"}
        can_resume = state == "paused"
        can_cancel = state in {"running", "queued", "paused"}
        return SpotifyBackfillSnapshot(
            csrf_token=csrf_token,
            can_run=self._spotify.is_authenticated(),
            default_max_items=default_max,
            expand_playlists=expand,
            options=options,
            last_job_id=status_payload.get("id") if status_payload else None,
            state=state,
            requested=requested,
            processed=processed,
            matched=matched,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            expanded_playlists=expanded_playlists,
            expanded_tracks=expanded_tracks,
            duration_ms=duration_ms,
            error=status_payload.get("error") if status_payload else None,
            can_pause=can_pause,
            can_resume=can_resume,
            can_cancel=can_cancel,
        )

    @staticmethod
    def _serialise_backfill_status(
        status: BackfillJobStatus | None,
    ) -> Mapping[str, object] | None:
        if status is None:
            return None
        return {
            "id": status.id,
            "state": status.state,
            "requested": status.requested_items,
            "processed": status.processed_items,
            "matched": status.matched_items,
            "cache_hits": status.cache_hits,
            "cache_misses": status.cache_misses,
            "expanded_playlists": status.expanded_playlists,
            "expanded_tracks": status.expanded_tracks,
            "duration_ms": status.duration_ms,
            "error": status.error,
            "expand_playlists": status.expand_playlists,
        }


def _build_spotify_service(
    request: Request,
    config: AppConfig,
    session_runner: SessionRunner,
) -> SpotifyDomainService:
    spotify_client = get_spotify_client()
    soulseek_client = get_soulseek_client()
    return SpotifyDomainService(
        config=config,
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        app_state=request.app.state,
        session_runner=session_runner,
    )


def get_spotify_ui_service(
    request: Request,
    config: AppConfig = Depends(get_app_config),
    db: Session = Depends(get_db),
    oauth: OAuthService = Depends(get_oauth_service),
    session_runner: SessionRunner = Depends(get_session_runner),
) -> SpotifyUiService:
    service = _build_spotify_service(request, config, session_runner)
    return SpotifyUiService(
        request=request,
        config=config,
        spotify_service=service,
        oauth_service=oauth,
        db_session=db,
    )


__all__ = [
    "SpotifyAccountSummary",
    "SpotifyTrackDetail",
    "SpotifyRecommendationRow",
    "SpotifyRecommendationSeed",
    "SpotifyBackfillSnapshot",
    "SpotifyBackfillOption",
    "SpotifyArtistRow",
    "SpotifySavedTrackRow",
    "SpotifyTopArtistRow",
    "SpotifyTopTrackRow",
    "SpotifyManualResult",
    "SpotifyOAuthHealth",
    "SpotifyPlaylistRow",
    "SpotifyPlaylistFilterOption",
    "SpotifyPlaylistFilters",
    "SpotifyFreeIngestAccepted",
    "SpotifyFreeIngestSkipped",
    "SpotifyFreeIngestResult",
    "SpotifyFreeIngestJobCounts",
    "SpotifyFreeIngestJobSnapshot",
    "SpotifyStatus",
    "SpotifyUiService",
    "get_spotify_ui_service",
]
