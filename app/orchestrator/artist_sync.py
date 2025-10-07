"""Artist synchronisation helpers for queue orchestration."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Mapping, Sequence

from app.integrations.artist_gateway import ArtistGateway, ArtistGatewayResponse
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.logging import get_logger
from app.logging_events import log_event
from app.services.artist_dao import ArtistDao, ArtistReleaseUpsertDTO, ArtistUpsertDTO
from app.utils.idempotency import make_idempotency_key
from app.workers import persistence
from app.workers.persistence import QueueJobDTO


logger = get_logger(__name__)

_JOB_TYPE = "artist_sync"
_LOG_COMPONENT = "queue.artist_sync"


@dataclass(slots=True)
class ArtistSyncHandlerDeps:
    """Resolved dependencies required by the artist sync handler."""

    gateway: ArtistGateway
    dao: ArtistDao
    providers: tuple[str, ...] = field(default_factory=lambda: ("spotify",))
    release_limit: int = 50
    now_factory: Callable[[], datetime] = datetime.utcnow


async def enqueue_artist_sync(
    artist_key: str,
    idempotency_hint: str | None = None,
    *,
    payload: Mapping[str, object] | None = None,
    priority: int = 0,
    persistence_module=persistence,
) -> QueueJobDTO:
    """Schedule an artist sync job while ensuring idempotency."""

    key = (artist_key or "").strip()
    if not key:
        raise ValueError("artist_key must be provided")

    job_payload: dict[str, object] = {"artist_key": key}
    if payload:
        for candidate, value in payload.items():
            if not isinstance(candidate, str) or not candidate:
                continue
            job_payload[candidate] = value

    serialised_hint = json.dumps(
        job_payload,
        sort_keys=True,
        default=str,
    )
    idempotency_key = make_idempotency_key(
        _JOB_TYPE,
        key,
        idempotency_hint or serialised_hint,
    )

    existing = persistence_module.find_by_idempotency(_JOB_TYPE, idempotency_key)
    if existing is not None:
        log_event(
            logger,
            "worker.job",
            component=_LOG_COMPONENT,
            status="deduplicated",
            job_type=_JOB_TYPE,
            entity_id=key,
            deduped=True,
        )
        return existing

    job = await persistence_module.enqueue_async(
        _JOB_TYPE,
        job_payload,
        priority=priority,
        idempotency_key=idempotency_key,
    )
    log_event(
        logger,
        "worker.job",
        component=_LOG_COMPONENT,
        status="enqueued",
        job_type=_JOB_TYPE,
        entity_id=key,
        deduped=False,
        priority=int(priority),
    )
    return job


def _split_artist_key(artist_key: str) -> tuple[str, str | None]:
    prefix, _, identifier = artist_key.partition(":")
    resolved_prefix = (prefix or "unknown").strip().lower()
    resolved_identifier = identifier.strip() if identifier else None
    return resolved_prefix or "unknown", resolved_identifier or None


def _select_artist(response: ArtistGatewayResponse, preferred_source: str) -> ProviderArtist | None:
    chosen: ProviderArtist | None = None
    for result in response.results:
        artist = result.artist
        if artist is None:
            continue
        if chosen is None:
            chosen = artist
        if artist.source and artist.source.lower() == preferred_source:
            return artist
    return chosen


def _build_artist_dto(
    artist_key: str,
    artist: ProviderArtist | None,
    *,
    fallback_source: str,
    fallback_id: str | None,
    fallback_name: str | None,
) -> ArtistUpsertDTO:
    if artist is None:
        name = fallback_name or artist_key
        return ArtistUpsertDTO(
            artist_key=artist_key,
            source=fallback_source,
            source_id=fallback_id,
            name=name,
        )
    return ArtistUpsertDTO(
        artist_key=artist_key,
        source=(artist.source or fallback_source),
        source_id=artist.source_id or fallback_id,
        name=artist.name or fallback_name or artist_key,
        genres=tuple(artist.genres or ()),
        images=tuple(artist.images or ()),
        popularity=artist.popularity,
        metadata=dict(artist.metadata or {}),
    )


def _build_release_dtos(
    artist_key: str, releases: Sequence[ProviderRelease]
) -> list[ArtistReleaseUpsertDTO]:
    items: list[ArtistReleaseUpsertDTO] = []
    for release in releases:
        title = (release.title or "").strip()
        if not title:
            continue
        items.append(
            ArtistReleaseUpsertDTO(
                artist_key=artist_key,
                source=(release.source or "unknown"),
                source_id=release.source_id,
                title=title,
                release_date=release.release_date,
                release_type=release.type,
                total_tracks=release.total_tracks,
                version=release.version,
                metadata=dict(release.metadata or {}),
            )
        )
    return items


async def handle_artist_sync(job: QueueJobDTO, deps: ArtistSyncHandlerDeps) -> Mapping[str, object]:
    payload = job.payload or {}
    artist_key = str(payload.get("artist_key") or "").strip()
    if not artist_key:
        log_event(
            logger,
            "worker.job",
            component=_LOG_COMPONENT,
            status="error",
            job_type=_JOB_TYPE,
            entity_id=None,
            error="missing_artist_key",
        )
        return {"status": "error", "error": "missing_artist_key"}

    source, source_id = _split_artist_key(artist_key)
    requested_providers = payload.get("providers")
    provider_candidates: Sequence[str] | None
    if isinstance(requested_providers, Sequence) and not isinstance(
        requested_providers, (str, bytes)
    ):
        cleaned: list[str] = []
        for value in requested_providers:
            text = str(value).strip()
            if text:
                cleaned.append(text)
        provider_candidates = cleaned
    else:
        provider_candidates = None
    providers = tuple(provider_candidates or deps.providers or (source,))
    if not providers:
        providers = (source,)

    release_limit = payload.get("release_limit")
    try:
        limit = int(release_limit) if release_limit is not None else int(deps.release_limit)
    except (TypeError, ValueError):
        limit = int(deps.release_limit)
    limit = max(1, limit)

    lookup_identifier = (
        source_id
        or str(payload.get("artist_id") or "").strip()
        or str(payload.get("artist_name") or "").strip()
        or artist_key
    )

    response = await deps.gateway.fetch_artist(lookup_identifier, providers=providers, limit=limit)
    provider_artist = _select_artist(response, source)
    payload_name = str(payload.get("artist_name") or "").strip()
    if provider_artist is not None and provider_artist.name:
        fallback_name = payload_name or provider_artist.name
    else:
        fallback_name = payload_name or None
    artist_dto = _build_artist_dto(
        artist_key,
        provider_artist,
        fallback_source=source,
        fallback_id=source_id,
        fallback_name=fallback_name,
    )

    artist_row = await asyncio.to_thread(deps.dao.upsert_artist, artist_dto)
    releases = _build_release_dtos(artist_key, response.releases)
    release_rows = await asyncio.to_thread(deps.dao.upsert_releases, releases)

    status = "ok" if release_rows or provider_artist is not None else "noop"
    log_event(
        logger,
        "worker.job",
        component=_LOG_COMPONENT,
        status=status,
        job_type=_JOB_TYPE,
        entity_id=artist_key,
        attempts=int(job.attempts or 0),
        release_count=len(release_rows),
        providers=",".join(providers),
    )

    return {
        "status": status,
        "artist_key": artist_key,
        "artist_id": artist_row.id,
        "artist_version": artist_row.version,
        "release_count": len(release_rows),
        "providers": list(providers),
    }


def build_artist_sync_handler(
    deps: ArtistSyncHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, object]]]:
    async def _handler(job: QueueJobDTO) -> Mapping[str, object]:
        return await handle_artist_sync(job, deps)

    return _handler


__all__ = [
    "ArtistSyncHandlerDeps",
    "build_artist_sync_handler",
    "enqueue_artist_sync",
    "handle_artist_sync",
]
