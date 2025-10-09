"""API router providing direct Spotify FREE playlist ingestion."""

from __future__ import annotations

from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, status

from app.config import AppConfig
from app.dependencies import (
    SessionRunner,
    get_app_config,
    get_session_runner,
    get_soulseek_client,
)
from app.errors import (
    AppError,
    InternalServerError,
    RateLimitedError,
    ValidationAppError,
)
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas.spotify_free_links import (
    AcceptedPlaylist,
    FreeLinksRequest,
    FreeLinksResponse,
    SkippedPlaylist,
)
from app.services.free_ingest_service import FreeIngestService, PlaylistEnqueueResult
from app.utils.spotify_url import parse_playlist_id

router = APIRouter(prefix="/spotify/free", tags=["Spotify FREE Links"])
_logger = get_logger(__name__)


def get_free_ingest_service(
    config=Depends(get_app_config),
    soulseek_client=Depends(get_soulseek_client),
    session_runner: SessionRunner = Depends(get_session_runner),
) -> FreeIngestService:
    return FreeIngestService(
        config=config,
        soulseek_client=soulseek_client,
        sync_worker=None,
        session_runner=session_runner,
    )


def _emit_api_event(
    request: Request,
    *,
    status_code: int,
    status_value: str,
    duration_ms: float,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "component": "api.spotify.free_links",
        "status": status_value,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "entity_id": getattr(request.state, "request_id", None),
    }
    if error:
        payload["error"] = error
    if meta:
        payload["meta"] = meta
    log_event(_logger, "api.request", **payload)


def _classify_invalid_reason(raw_url: str, *, allow_user_urls: bool) -> str:
    text = (raw_url or "").strip()
    if text.lower().startswith("spotify:"):
        parts = [segment for segment in text.split(":") if segment]
        if len(parts) < 2:
            return "invalid"
        kind = parts[1].lower()
        if kind == "playlist":
            return "invalid"
        if kind == "user":
            if not allow_user_urls:
                return "non_playlist"
            if len(parts) < 5:
                return "invalid"
            if parts[3].lower() != "playlist":
                return "non_playlist"
            return "invalid"
        return "non_playlist"

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return "invalid"
    if parsed.netloc.lower() != "open.spotify.com":
        return "invalid"
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and segments[0].lower().startswith("intl-"):
        segments = segments[1:]
    if not segments:
        return "invalid"
    head = segments[0].lower()
    if head == "playlist":
        return "invalid"
    if head == "user":
        if not allow_user_urls:
            return "non_playlist"
        if len(segments) < 4:
            return "invalid"
        if segments[2].lower() != "playlist":
            return "non_playlist"
        return "invalid"
    return "non_playlist"


def _canonical_playlist_url(playlist_id: str) -> str:
    return f"https://open.spotify.com/playlist/{playlist_id}"


@router.post("/links", response_model=FreeLinksResponse)
async def submit_playlist_links(
    payload: FreeLinksRequest,
    request: Request,
    service: FreeIngestService = Depends(get_free_ingest_service),
    config: AppConfig = Depends(get_app_config),
) -> FreeLinksResponse:
    started = perf_counter()
    raw_urls = list(payload.iter_urls())
    if not raw_urls:
        raise ValidationAppError("url or urls must be provided")

    accepted: list[AcceptedPlaylist] = []
    skipped: list[SkippedPlaylist] = []
    unique_ids: list[str] = []
    origin_map: dict[str, str] = {}
    seen: set[str] = set()

    for raw in raw_urls:
        text = (raw or "").strip()
        if not text:
            skipped.append(SkippedPlaylist(url=raw, reason="invalid"))
            continue
        playlist_id = parse_playlist_id(
            text,
            allow_user_urls=config.spotify.free_accept_user_urls,
        )
        if playlist_id is None:
            reason = _classify_invalid_reason(
                text,
                allow_user_urls=config.spotify.free_accept_user_urls,
            )
            skipped.append(SkippedPlaylist(url=raw, reason=reason))
            continue
        if playlist_id in seen:
            skipped.append(SkippedPlaylist(url=raw, reason="duplicate"))
            continue
        seen.add(playlist_id)
        origin_map[playlist_id] = raw
        unique_ids.append(playlist_id)

    if unique_ids:
        try:
            outcome = await service.enqueue_playlists(unique_ids)
        except AppError as exc:
            duration_ms = (perf_counter() - started) * 1000
            _emit_api_event(
                request,
                status_code=exc.http_status,
                status_value="error",
                duration_ms=duration_ms,
                error=exc.code,
                meta={"accepted": 0, "skipped": len(skipped)},
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            duration_ms = (perf_counter() - started) * 1000
            _emit_api_event(
                request,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                status_value="error",
                duration_ms=duration_ms,
                error="unexpected_error",
                meta={"accepted": 0, "skipped": len(skipped)},
            )
            raise InternalServerError("Failed to enqueue playlists.") from exc
    else:
        outcome = PlaylistEnqueueResult(accepted_ids=[], duplicate_ids=[])

    if outcome.error == "backpressure":
        duration_ms = (perf_counter() - started) * 1000
        rate_error = RateLimitedError("Too many ingest jobs in progress.")
        _emit_api_event(
            request,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            status_value="error",
            duration_ms=duration_ms,
            error=rate_error.code,
            meta={"accepted": 0, "skipped": len(skipped)},
        )
        raise rate_error

    accepted_ids = set(outcome.accepted_ids)
    duplicate_ids = set(outcome.duplicate_ids)

    for playlist_id in unique_ids:
        if playlist_id in accepted_ids:
            accepted.append(
                AcceptedPlaylist(
                    playlist_id=playlist_id,
                    url=_canonical_playlist_url(playlist_id),
                )
            )
        else:
            skipped.append(
                SkippedPlaylist(
                    url=origin_map.get(
                        playlist_id, _canonical_playlist_url(playlist_id)
                    ),
                    reason="duplicate",
                )
            )

    extra_duplicates = duplicate_ids.difference(seen)
    for playlist_id in extra_duplicates:
        skipped.append(
            SkippedPlaylist(
                url=_canonical_playlist_url(playlist_id),
                reason="duplicate",
            )
        )

    response = FreeLinksResponse(accepted=accepted, skipped=skipped)
    duration_ms = (perf_counter() - started) * 1000
    _emit_api_event(
        request,
        status_code=status.HTTP_200_OK,
        status_value="ok",
        duration_ms=duration_ms,
        meta={"accepted": len(response.accepted), "skipped": len(response.skipped)},
    )
    return response
