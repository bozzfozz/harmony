"""Artist synchronisation handler coordinating provider fetches and persistence."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Awaitable, Callable, Mapping, Sequence

from app.dependencies import get_app_config
from app.integrations.artist_gateway import ArtistGateway, ArtistGatewayResponse
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.integrations.provider_gateway import (
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
)
from app.logging import get_logger
from app.logging_events import log_event
from app.services.artist_dao import (
    ArtistDao,
    ArtistReleaseRow,
    ArtistReleaseUpsertDTO,
    ArtistUpsertDTO,
)
from app.services.artist_delta import (
    ArtistLocalState,
    ArtistRemoteState,
    ReleaseSnapshot,
    determine_delta,
)
from app.services.audit import write_audit
from app.services.cache import ResponseCache, build_path_param_hash
from app.utils.idempotency import make_idempotency_key
from app.workers import persistence
from app.workers.persistence import QueueJobDTO


logger = get_logger(__name__)

_JOB_TYPE = "artist_sync"
_LOG_COMPONENT = "orchestrator.artist_sync"
_DEFAULT_RELEASE_LIMIT = 50
_DEFAULT_PROVIDERS: tuple[str, ...] = ("spotify",)


def _coerce_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return _coerce_int(value, default)


@dataclass(slots=True)
class ArtistSyncHandlerDeps:
    """Resolved dependencies used by the artist sync handler."""

    gateway: ArtistGateway
    dao: ArtistDao = field(default_factory=ArtistDao)
    response_cache: ResponseCache | None = None
    providers: Sequence[str] = field(default_factory=lambda: _DEFAULT_PROVIDERS)
    release_limit: int = _DEFAULT_RELEASE_LIMIT
    now_factory: Callable[[], datetime] = datetime.utcnow
    cooldown_minutes: int | None = None
    priority_decay: int = field(
        default_factory=lambda: max(0, _env_int("ARTIST_SYNC_PRIORITY_DECAY", 0))
    )
    prune_removed: bool = field(
        default_factory=lambda: _coerce_bool(os.getenv("ARTIST_SYNC_PRUNE"), False)
    )
    hard_delete_removed: bool = field(
        default_factory=lambda: _coerce_bool(os.getenv("ARTIST_SYNC_HARD_DELETE"), False)
    )
    api_base_path: str | None = None

    def __post_init__(self) -> None:
        config = get_app_config()
        if self.cooldown_minutes is None:
            self.cooldown_minutes = _coerce_int(config.watchlist.cooldown_minutes, 0)
        else:
            self.cooldown_minutes = _coerce_int(self.cooldown_minutes, 0)
        self.priority_decay = max(0, _coerce_int(self.priority_decay, 0))
        resolved_limit = _coerce_int(self.release_limit, _DEFAULT_RELEASE_LIMIT)
        self.release_limit = max(1, resolved_limit)
        provider_list: list[str] = []
        for provider in self.providers:
            text = str(provider).strip()
            if text:
                provider_list.append(text)
        if not provider_list:
            provider_list = list(_DEFAULT_PROVIDERS)
        self.providers = tuple(dict.fromkeys(provider_list))  # preserve order, dedupe
        if self.api_base_path is None:
            base_path = config.api_base_path or ""
            if base_path and not base_path.startswith("/"):
                base_path = f"/{base_path}"
            self.api_base_path = base_path
        artist_sync = getattr(config, "artist_sync", None)
        if artist_sync is not None:
            self.prune_removed = bool(artist_sync.prune_removed)
            self.hard_delete_removed = bool(artist_sync.hard_delete)


async def enqueue_artist_sync(
    artist_key: str,
    *,
    force: bool = False,
    payload: Mapping[str, object] | None = None,
    priority: int = 0,
    persistence_module=persistence,
) -> QueueJobDTO:
    """Enqueue an artist sync job while enforcing idempotency."""

    key = (artist_key or "").strip()
    if not key:
        raise ValueError("artist_key must be provided")

    job_payload: dict[str, object] = {"artist_key": key, "force": bool(force)}
    if payload:
        for candidate, value in payload.items():
            if not isinstance(candidate, str) or not candidate:
                continue
            job_payload[candidate] = value

    args_hash = json.dumps(job_payload, sort_keys=True, default=str)
    idempotency_key = make_idempotency_key(_JOB_TYPE, key, args_hash)

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
        priority=int(priority),
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


def _resolve_providers(
    payload: Mapping[str, object],
    *,
    default: Sequence[str],
    fallback_source: str,
) -> tuple[str, ...]:
    requested = payload.get("providers")
    if isinstance(requested, Sequence) and not isinstance(requested, (str, bytes)):
        cleaned: list[str] = []
        for value in requested:
            text = str(value).strip()
            if text:
                cleaned.append(text)
        if cleaned:
            return tuple(dict.fromkeys(cleaned))
    if default:
        return tuple(default)
    return (fallback_source,)


def _resolve_release_limit(payload: Mapping[str, object], fallback: int) -> int:
    raw_limit = payload.get("release_limit")
    limit = _coerce_int(raw_limit, fallback)
    return max(1, limit)


def _cooldown_until(now: datetime, minutes: int, *, force: bool) -> datetime | None:
    if force:
        return now
    if minutes <= 0:
        return now
    return now + timedelta(minutes=minutes)


def _dependency_status(error_count: int, provider_count: int) -> str:
    if error_count <= 0:
        return "ok"
    if error_count >= max(provider_count, 1):
        return "failed"
    return "partial"


def _is_retryable_error(error: ProviderGatewayError) -> bool:
    return isinstance(
        error,
        (
            ProviderGatewayTimeoutError,
            ProviderGatewayRateLimitedError,
            ProviderGatewayDependencyError,
        ),
    )


def _normalise_alias_sequence(values: object | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        candidates = [values]
    elif isinstance(values, Mapping):
        candidates = list(values.values())
    else:
        try:
            candidates = list(values)  # type: ignore[arg-type]
        except TypeError:
            candidates = [values]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


def _extract_aliases(metadata: Mapping[str, object] | None) -> tuple[str, ...]:
    if not isinstance(metadata, Mapping):
        return ()
    return _normalise_alias_sequence(metadata.get("aliases"))


def _normalise_release_date_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return ""
    if len(text) == 4 and text.isdigit():
        return text
    if len(text) == 7 and text[:4].isdigit():
        return text
    return text


def _release_identity_for_row(row: ArtistReleaseRow) -> tuple[str, ...]:
    source = (row.source or "unknown").strip().lower()
    source_id = (row.source_id or "").strip()
    if source_id:
        return ("id", source, source_id)
    return (
        "composite",
        source,
        (row.title or "").strip().casefold(),
        _normalise_release_date_value(row.release_date),
        (row.release_type or "").strip().casefold(),
    )


def _release_identity_for_dto(dto: ArtistReleaseUpsertDTO) -> tuple[str, ...]:
    source = (dto.source or "unknown").strip().lower()
    source_id = (dto.source_id or "").strip()
    if source_id:
        return ("id", source, source_id)
    return (
        "composite",
        source,
        (dto.title or "").strip().casefold(),
        _normalise_release_date_value(dto.release_date),
        (dto.release_type or "").strip().casefold(),
    )


def _release_audit_payload_from_row(row: ArtistReleaseRow | None) -> Mapping[str, object] | None:
    if row is None:
        return None
    return {
        "source": row.source,
        "source_id": row.source_id,
        "title": row.title,
        "release_date": row.release_date.isoformat() if row.release_date else None,
        "release_type": row.release_type,
        "total_tracks": row.total_tracks,
        "inactive_at": row.inactive_at.isoformat() if row.inactive_at else None,
        "inactive_reason": row.inactive_reason,
    }


def _release_audit_payload_from_snapshot(snapshot: ReleaseSnapshot) -> Mapping[str, object]:
    return {
        "source": snapshot.source,
        "source_id": snapshot.source_id,
        "title": snapshot.title,
        "release_date": snapshot.release_date.isoformat() if snapshot.release_date else None,
        "release_type": snapshot.release_type,
        "total_tracks": snapshot.total_tracks,
        "inactive_at": snapshot.inactive_at.isoformat() if snapshot.inactive_at else None,
        "inactive_reason": snapshot.inactive_reason,
    }


async def handle_artist_sync(
    job: QueueJobDTO,
    deps: ArtistSyncHandlerDeps,
) -> Mapping[str, Any]:
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

    attempts = int(job.attempts or 0)
    started = perf_counter()
    force_sync = _coerce_bool(payload.get("force"), False)
    log_event(
        logger,
        "worker.job",
        component=_LOG_COMPONENT,
        status="start",
        job_type=_JOB_TYPE,
        entity_id=artist_key,
        attempts=attempts,
        force=force_sync,
    )

    now = deps.now_factory().replace(tzinfo=None)
    source, source_id = _split_artist_key(artist_key)
    providers = _resolve_providers(payload, default=deps.providers, fallback_source=source)
    release_limit = _resolve_release_limit(payload, deps.release_limit)
    lookup_identifier = (
        source_id
        or str(payload.get("artist_id") or "").strip()
        or str(payload.get("artist_name") or "").strip()
        or artist_key
    )

    dependency_started = perf_counter()
    try:
        response = await deps.gateway.fetch_artist(
            lookup_identifier,
            providers=providers,
            limit=release_limit,
        )
    except ProviderGatewayError as exc:
        duration_ms = (perf_counter() - dependency_started) * 1000
        log_event(
            logger,
            "api.dependency",
            component=_LOG_COMPONENT,
            dependency="provider_gateway",
            status="error",
            duration_ms=round(duration_ms, 3),
            entity_id=artist_key,
            error=getattr(exc, "__class__", type(exc)).__name__,
            retryable=_is_retryable_error(exc),
        )
        log_event(
            logger,
            "worker.job",
            component=_LOG_COMPONENT,
            status="error",
            job_type=_JOB_TYPE,
            entity_id=artist_key,
            attempts=attempts,
            error="provider_error",
        )
        raise

    dependency_duration = (perf_counter() - dependency_started) * 1000
    errors = {
        provider_result.provider: provider_result.error
        for provider_result in response.results
        if provider_result.error
    }
    status = _dependency_status(len(errors), len(providers))
    log_event(
        logger,
        "api.dependency",
        component=_LOG_COMPONENT,
        dependency="provider_gateway",
        status=status,
        duration_ms=round(dependency_duration, 3),
        entity_id=artist_key,
        meta={
            "providers": list(providers),
            "error_count": len(errors),
        },
    )
    for provider, error in errors.items():
        if error is None:
            continue
        log_event(
            logger,
            "api.dependency",
            component=_LOG_COMPONENT,
            dependency=f"provider.{provider}",
            status="error",
            entity_id=artist_key,
            error=error.__class__.__name__,
            retryable=_is_retryable_error(error),
        )

    if errors and len(errors) == len(providers):
        first_error = next(iter(errors.values()))
        error_name = first_error.__class__.__name__ if first_error else "provider_error"
        log_event(
            logger,
            "worker.job",
            component=_LOG_COMPONENT,
            status="error",
            job_type=_JOB_TYPE,
            entity_id=artist_key,
            attempts=attempts,
            error=error_name,
        )
        raise first_error or ProviderGatewayError("unknown", "All providers failed")

    provider_artist = _select_artist(response, source)
    payload_name = str(payload.get("artist_name") or "").strip() or None
    fallback_name = (
        provider_artist.name
        if provider_artist and provider_artist.name
        else payload_name or artist_key
    )
    artist_dto = _build_artist_dto(
        artist_key,
        provider_artist,
        fallback_source=source,
        fallback_id=source_id,
        fallback_name=fallback_name,
    )

    releases = _build_release_dtos(artist_key, response.releases)

    existing_artist_row = await asyncio.to_thread(deps.dao.get_artist, artist_key)
    existing_release_rows = await asyncio.to_thread(
        deps.dao.get_artist_releases, artist_key, include_inactive=True
    )
    local_state = ArtistLocalState(
        releases=tuple(ReleaseSnapshot.from_row(row) for row in existing_release_rows),
        aliases=_extract_aliases(existing_artist_row.metadata if existing_artist_row else None),
    )
    remote_state = ArtistRemoteState(
        releases=tuple(releases),
        aliases=_extract_aliases(artist_dto.metadata),
    )
    delta = determine_delta(local_state, remote_state)

    artist_row = await asyncio.to_thread(deps.dao.upsert_artist, artist_dto)

    upsert_targets = list(delta.releases.added) + [change.after for change in delta.releases.updated]
    persisted_rows: list[ArtistReleaseRow] = []
    if upsert_targets:
        persisted_rows = await asyncio.to_thread(deps.dao.upsert_releases, upsert_targets)

    inactive_rows: list[ArtistReleaseRow] = []
    if deps.prune_removed and delta.releases.removed:
        ids_to_prune = [snapshot.id for snapshot in delta.releases.removed]
        inactive_rows = await asyncio.to_thread(
            deps.dao.mark_releases_inactive,
            ids_to_prune,
            reason="pruned",
            hard_delete=bool(deps.hard_delete_removed),
        )

    added_count = len(delta.releases.added)
    updated_count = len(delta.releases.updated)
    alias_added = len(delta.aliases.added)
    alias_removed = len(delta.aliases.removed)
    removed_count = len(delta.releases.removed)
    if deps.prune_removed:
        inactivated_count = (
            removed_count if deps.hard_delete_removed else len(inactive_rows)
        )
    else:
        inactivated_count = 0

    existing_ids = {snapshot.id for snapshot in local_state.releases}
    persisted_by_id = {row.id: row for row in persisted_rows}
    new_rows = [row for row in persisted_rows if row.id not in existing_ids]
    new_identity_map = {_release_identity_for_row(row): row for row in new_rows}
    inactive_map = {row.id: row for row in inactive_rows}
    local_aliases = tuple(local_state.aliases)
    remote_aliases = tuple(remote_state.aliases)

    audit_tasks: list[asyncio.Future[Any]] = []
    job_identifier = job.id
    for dto in delta.releases.added:
        row = new_identity_map.get(_release_identity_for_dto(dto))
        if row is None:
            continue
        audit_tasks.append(
            asyncio.to_thread(
                write_audit,
                event="created",
                entity_type="release",
                artist_key=artist_key,
                entity_id=row.id,
                job_id=job_identifier,
                before=None,
                after=_release_audit_payload_from_row(row),
            )
        )
    for change in delta.releases.updated:
        after_row = persisted_by_id.get(change.before.id)
        if after_row is None:
            continue
        audit_tasks.append(
            asyncio.to_thread(
                write_audit,
                event="updated",
                entity_type="release",
                artist_key=artist_key,
                entity_id=after_row.id,
                job_id=job_identifier,
                before=_release_audit_payload_from_snapshot(change.before),
                after=_release_audit_payload_from_row(after_row),
            )
        )
    if deps.prune_removed:
        for snapshot in delta.releases.removed:
            after_row = inactive_map.get(snapshot.id)
            after_payload = (
                _release_audit_payload_from_row(after_row)
                if after_row is not None
                else {
                    "inactive_reason": "pruned",
                    "inactive": True,
                    "deleted": bool(deps.hard_delete_removed),
                }
            )
            audit_tasks.append(
                asyncio.to_thread(
                    write_audit,
                    event="inactivated",
                    entity_type="release",
                    artist_key=artist_key,
                    entity_id=snapshot.id,
                    job_id=job_identifier,
                    before=_release_audit_payload_from_snapshot(snapshot),
                    after=after_payload,
                )
            )
    if alias_added or alias_removed:
        audit_tasks.append(
            asyncio.to_thread(
                write_audit,
                event="updated",
                entity_type="alias",
                artist_key=artist_key,
                entity_id=None,
                job_id=job_identifier,
                before={"aliases": list(local_aliases)},
                after={"aliases": list(remote_aliases)},
            )
        )

    cooldown = _cooldown_until(now, int(deps.cooldown_minutes or 0), force=force_sync)
    decay = deps.priority_decay if not force_sync and deps.priority_decay > 0 else 0
    watchlist_updated = await asyncio.to_thread(
        deps.dao.mark_synced,
        artist_key,
        synced_at=now,
        cooldown_until=cooldown,
        priority_decay=decay if decay > 0 else None,
    )

    cache_evicted = await _evict_cache(deps, artist_key)

    if audit_tasks:
        await asyncio.gather(*audit_tasks)

    artist_created = existing_artist_row is None
    total_changes = added_count + updated_count + (inactivated_count if deps.prune_removed else 0)
    if alias_added or alias_removed:
        total_changes += 1
    if artist_created:
        total_changes += 1
    result_status = "ok" if total_changes > 0 or provider_artist is not None else "noop"
    duration_ms = (perf_counter() - started) * 1000
    log_event(
        logger,
        "worker.job",
        component=_LOG_COMPONENT,
        status=result_status,
        job_type=_JOB_TYPE,
        entity_id=artist_key,
        attempts=attempts,
        release_count=len(persisted_rows),
        providers=",".join(providers),
        watchlist_updated=bool(watchlist_updated),
        cache_evicted=int(cache_evicted),
        artist_created=bool(artist_created),
        added_releases=added_count,
        updated_releases=updated_count,
        inactivated_releases=inactivated_count,
        alias_added=alias_added,
        alias_removed=alias_removed,
        duration_ms=round(duration_ms, 3),
        force=force_sync,
    )

    return {
        "status": result_status,
        "artist_key": artist_key,
        "artist_id": artist_row.id,
        "artist_version": artist_row.version,
        "release_count": len(persisted_rows),
        "providers": list(providers),
        "watchlist_updated": bool(watchlist_updated),
        "cache_evicted": int(cache_evicted),
        "added_releases": added_count,
        "updated_releases": updated_count,
        "inactivated_releases": inactivated_count,
        "alias_added": alias_added,
        "alias_removed": alias_removed,
    }


async def _evict_cache(deps: ArtistSyncHandlerDeps, artist_key: str) -> int:
    cache = deps.response_cache
    if cache is None or not getattr(cache, "write_through", True):
        return 0
    templates = _cache_templates(deps.api_base_path)
    path_hash = build_path_param_hash({"artist_key": artist_key})
    evicted = 0
    for template in templates:
        prefix = f"GET:{template}:{path_hash}:"
        evicted += await cache.invalidate_prefix(
            prefix,
            reason="artist_sync",
            entity_id=artist_key,
            path=template,
        )
    return evicted


def _cache_templates(base_path: str | None) -> tuple[str, ...]:
    detail_template = "/artists/{artist_key}"
    templates = [detail_template]
    if base_path:
        normalized = base_path.rstrip("/")
        if normalized:
            templates.append(f"{normalized}{detail_template}")
    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for template in templates:
        if template not in seen:
            ordered.append(template)
            seen.add(template)
    return tuple(ordered)


def build_artist_sync_handler(
    deps: ArtistSyncHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    async def _handler(job: QueueJobDTO) -> Mapping[str, Any]:
        return await handle_artist_sync(job, deps)

    return _handler


__all__ = [
    "ArtistSyncHandlerDeps",
    "build_artist_sync_handler",
    "enqueue_artist_sync",
    "handle_artist_sync",
]
