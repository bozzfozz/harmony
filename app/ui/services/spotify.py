from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
from app.services.oauth_service import OAuthManualRequest, OAuthManualResponse, OAuthService
from app.services.spotify_domain_service import SpotifyDomainService, SpotifyServiceStatus

logger = get_logger(__name__)


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
class SpotifyArtistRow:
    identifier: str
    name: str
    followers: int
    popularity: int
    genres: tuple[str, ...]


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


@dataclass(slots=True)
class SpotifyTopArtistRow:
    identifier: str
    name: str
    followers: int
    popularity: int
    genres: tuple[str, ...]
    rank: int


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


@dataclass(slots=True)
class SpotifyBackfillSnapshot:
    csrf_token: str
    can_run: bool
    default_max_items: int | None
    expand_playlists: bool
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

    def list_playlists(self) -> Sequence[SpotifyPlaylistRow]:
        playlists = self._spotify.list_playlists(self._db)
        rows = [
            SpotifyPlaylistRow(
                identifier=playlist.id,
                name=playlist.name,
                track_count=int(playlist.track_count or 0),
                updated_at=playlist.updated_at or datetime.utcnow(),
            )
            for playlist in playlists
        ]
        logger.debug("spotify.ui.playlists", extra={"count": len(rows)})
        return tuple(rows)

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

            rows.append(
                SpotifyArtistRow(
                    identifier=identifier,
                    name=name,
                    followers=followers,
                    popularity=popularity,
                    genres=tuple(genres_list),
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

    @staticmethod
    def _clean_track_uris(uris: Sequence[str]) -> tuple[str, ...]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for uri in uris:
            candidate = str(uri or "").strip()
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            cleaned.append(candidate)
            seen.add(key)
        return tuple(cleaned)

    def add_tracks_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> int:
        playlist_key = str(playlist_id or "").strip()
        if not playlist_key:
            raise ValueError("A Spotify playlist identifier is required.")
        cleaned = self._clean_track_uris(uris)
        if not cleaned:
            raise ValueError("At least one Spotify track URI is required.")
        self._spotify.add_tracks_to_playlist(playlist_key, cleaned)
        logger.info(
            "spotify.ui.playlists.add_tracks",
            extra={"playlist_id": playlist_key, "count": len(cleaned)},
        )
        return len(cleaned)

    def remove_tracks_from_playlist(self, playlist_id: str, uris: Sequence[str]) -> int:
        playlist_key = str(playlist_id or "").strip()
        if not playlist_key:
            raise ValueError("A Spotify playlist identifier is required.")
        cleaned = self._clean_track_uris(uris)
        if not cleaned:
            raise ValueError("At least one Spotify track URI is required.")
        self._spotify.remove_tracks_from_playlist(playlist_key, cleaned)
        logger.info(
            "spotify.ui.playlists.remove_tracks",
            extra={"playlist_id": playlist_key, "count": len(cleaned)},
        )
        return len(cleaned)

    def reorder_playlist(
        self,
        playlist_id: str,
        *,
        range_start: int,
        insert_before: int,
    ) -> None:
        playlist_key = str(playlist_id or "").strip()
        if not playlist_key:
            raise ValueError("A Spotify playlist identifier is required.")
        try:
            start_value = int(range_start)
            target_value = int(insert_before)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
            raise ValueError("Valid start and insert positions are required.") from exc
        if start_value < 0 or target_value < 0:
            raise ValueError("Positions must be zero or greater.")
        self._spotify.reorder_playlist(
            playlist_key,
            range_start=start_value,
            insert_before=target_value,
        )
        logger.info(
            "spotify.ui.playlists.reorder",
            extra={
                "playlist_id": playlist_key,
                "range_start": start_value,
                "insert_before": target_value,
            },
        )

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
            rows.append(
                SpotifyRecommendationRow(
                    identifier=identifier,
                    name=name,
                    artists=tuple(artist_names),
                    album=album,
                    preview_url=preview_url,
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
            product=product,
            followers=followers,
            country=country,
        )

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

    def top_tracks(self, *, limit: int = 20) -> Sequence[SpotifyTopTrackRow]:
        page_limit = max(1, min(int(limit), 50))
        items = self._spotify.get_top_tracks(limit=page_limit)
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

                rows.append(
                    SpotifyTopTrackRow(
                        identifier=identifier,
                        name=name,
                        artists=tuple(artist_names),
                        album=album,
                        popularity=popularity,
                        duration_ms=duration_ms,
                        rank=index,
                    )
                )

        logger.debug(
            "spotify.ui.top_tracks",
            extra={"count": len(rows), "limit": page_limit},
        )
        return tuple(rows)

    def top_artists(self, *, limit: int = 20) -> Sequence[SpotifyTopArtistRow]:
        page_limit = max(1, min(int(limit), 50))
        items = self._spotify.get_top_artists(limit=page_limit)
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

                rows.append(
                    SpotifyTopArtistRow(
                        identifier=identifier,
                        name=name,
                        followers=followers,
                        popularity=popularity,
                        genres=tuple(genres),
                        rank=index,
                    )
                )

        logger.debug(
            "spotify.ui.top_artists",
            extra={"count": len(rows), "limit": page_limit},
        )
        return tuple(rows)

    def backfill_status(self, job_id: str | None) -> Mapping[str, object] | None:
        if not job_id:
            return None
        status = self._spotify.get_backfill_status(job_id)
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
        return SpotifyBackfillSnapshot(
            csrf_token=csrf_token,
            can_run=self._spotify.is_authenticated(),
            default_max_items=default_max,
            expand_playlists=expand,
            last_job_id=status_payload.get("id") if status_payload else None,
            state=status_payload.get("state") if status_payload else None,
            requested=requested,
            processed=processed,
            matched=matched,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            expanded_playlists=expanded_playlists,
            expanded_tracks=expanded_tracks,
            duration_ms=duration_ms,
            error=status_payload.get("error") if status_payload else None,
        )


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
    "SpotifyRecommendationRow",
    "SpotifyRecommendationSeed",
    "SpotifyBackfillSnapshot",
    "SpotifyArtistRow",
    "SpotifySavedTrackRow",
    "SpotifyTopArtistRow",
    "SpotifyTopTrackRow",
    "SpotifyManualResult",
    "SpotifyOAuthHealth",
    "SpotifyPlaylistRow",
    "SpotifyStatus",
    "SpotifyUiService",
    "get_spotify_ui_service",
]
