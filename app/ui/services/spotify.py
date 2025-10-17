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
    "SpotifyBackfillSnapshot",
    "SpotifyArtistRow",
    "SpotifyManualResult",
    "SpotifyOAuthHealth",
    "SpotifyPlaylistRow",
    "SpotifyStatus",
    "SpotifyUiService",
    "get_spotify_ui_service",
]
