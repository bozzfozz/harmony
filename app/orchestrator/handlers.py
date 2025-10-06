"""Utilities coordinating orchestrated background work."""

from __future__ import annotations

import asyncio
import inspect
import os
import random
import statistics
import time
from contextlib import AbstractContextManager
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
)

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import WatchlistWorkerConfig, settings
from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import run_session, session_scope
from app.integrations.normalizers import normalize_slskd_candidate, normalize_spotify_track
from app.logging import get_logger
from app.logging_events import log_event
from app.models import Download, IngestItem, IngestItemState, Match
from app.services.artist_delta import (
    AlbumRelease,
    ArtistCacheHint,
    ArtistDelta,
    ArtistTrackCandidate,
    build_artist_delta,
    filter_new_releases,
)
from app.services.backfill_service import BackfillJobStatus
from app.services.retry_policy_provider import (
    RetryPolicy,
    RetryPolicyProvider,
    get_retry_policy_provider,
)
from app.services.watchlist_dao import WatchlistArtistRow, WatchlistDAO

if TYPE_CHECKING:  # pragma: no cover - typing imports only
    from app.services.free_ingest_service import IngestSubmission, JobStatus
from app.services.spotify_domain_service import SpotifyDomainService
from app.utils.activity import record_activity
from app.utils.events import (
    DOWNLOAD_RETRY_COMPLETED,
    DOWNLOAD_RETRY_FAILED,
    DOWNLOAD_RETRY_SCHEDULED,
)
from app.utils.file_utils import organize_file
from app.workers import persistence
from app.workers.persistence import QueueJobDTO


logger = get_logger(__name__)

_DEFAULT_TIMEOUT_MS = 10_000
_RETRY_DEFAULT_SCAN_INTERVAL = 60.0
_RETRY_DEFAULT_BATCH_LIMIT = 100
_WATCHLIST_MAX_BACKOFF_MS = 5_000
_WATCHLIST_LOG_COMPONENT = "orchestrator.watchlist"
_ARTIST_REFRESH_LOG_COMPONENT = "orchestrator.artist_refresh"


SyncRetryPolicy = RetryPolicy


def _safe_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _safe_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _coerce_positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _coerce_priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def load_sync_retry_policy(
    *,
    max_attempts: int | None = None,
    base_seconds: float | None = None,
    jitter_pct: float | None = None,
    env: Mapping[str, Any] | None = None,
    defaults: Any | None = None,
    force_reload: bool = False,
    job_type: str = "sync",
) -> SyncRetryPolicy:
    """Resolve the retry policy honouring runtime overrides.

    Precedence: explicit keyword arguments → provided ``defaults``
    → live environment overrides → code defaults from :mod:`app.config`.
    """

    base_policy: RetryPolicy
    if env is not None:
        provider = RetryPolicyProvider(env_source=lambda env_map=env: env_map, reload_interval=0)
        base_policy = provider.get_retry_policy(job_type)
    else:
        provider = get_retry_policy_provider()
        if force_reload:
            provider.invalidate(job_type)
        base_policy = provider.get_retry_policy(job_type)

    if defaults is not None:
        base_policy = RetryPolicy(
            max_attempts=_coerce_positive_int(
                getattr(defaults, "max_attempts", base_policy.max_attempts),
                base_policy.max_attempts,
            ),
            base_seconds=_coerce_positive_float(
                getattr(defaults, "base_seconds", base_policy.base_seconds),
                base_policy.base_seconds,
            ),
            jitter_pct=float(getattr(defaults, "jitter_pct", base_policy.jitter_pct)),
            timeout_seconds=getattr(defaults, "timeout_seconds", base_policy.timeout_seconds),
        )

    resolved_max = _coerce_positive_int(
        base_policy.max_attempts if max_attempts is None else max_attempts,
        base_policy.max_attempts,
    )
    resolved_base = _coerce_positive_float(
        base_policy.base_seconds if base_seconds is None else base_seconds,
        base_policy.base_seconds,
    )

    resolved_jitter = base_policy.jitter_pct if jitter_pct is None else float(jitter_pct)
    if resolved_jitter < 0:
        resolved_jitter = 0.0

    return RetryPolicy(
        max_attempts=int(resolved_max),
        base_seconds=float(resolved_base),
        jitter_pct=float(resolved_jitter),
        timeout_seconds=base_policy.timeout_seconds,
    )


def refresh_sync_retry_policy(
    env: Mapping[str, Any] | None = None, *, job_type: str = "sync"
) -> SyncRetryPolicy:
    """Force a refresh of the cached retry policy defaults and return the snapshot."""

    if env is not None:
        provider = RetryPolicyProvider(env_source=lambda env_map=env: env_map, reload_interval=0)
        return provider.get_retry_policy(job_type)

    provider = get_retry_policy_provider()
    provider.invalidate(job_type)
    return provider.get_retry_policy(job_type)


def calculate_retry_backoff_seconds(
    attempt: int, policy: SyncRetryPolicy, rng: random.Random
) -> float:
    """Return the retry delay for a given attempt applying jitter."""

    bounded_attempt = max(0, min(attempt, 6))
    delay = policy.base_seconds * (2**bounded_attempt)
    jitter_pct = max(0.0, policy.jitter_pct)
    if jitter_pct:
        jitter_factor = rng.uniform(1 - jitter_pct, 1 + jitter_pct)
    else:
        jitter_factor = 1.0
    return max(0.0, delay * jitter_factor)


def truncate_error(message: str, limit: int = 512) -> str:
    text = message.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _resolve_timeout_ms(value: str | None) -> int:
    timeout = _safe_int(value, _DEFAULT_TIMEOUT_MS)
    return max(1_000, timeout) if timeout > 0 else _DEFAULT_TIMEOUT_MS


async def enqueue_sync_job(
    payload: Mapping[str, Any],
    *,
    priority: int | None = None,
    idempotency_key: str | None = None,
) -> QueueJobDTO | None:
    return await asyncio.to_thread(
        persistence.enqueue,
        "sync",
        payload,
        priority=priority,
        idempotency_key=idempotency_key,
    )


async def enqueue_artist_delta_job(
    payload: Mapping[str, Any],
    *,
    priority: int | None = None,
    idempotency_key: str | None = None,
) -> QueueJobDTO | None:
    return await asyncio.to_thread(
        persistence.enqueue,
        "artist_delta",
        payload,
        priority=priority,
        idempotency_key=idempotency_key,
    )


async def enqueue_retry_scan_job(
    *,
    delay_seconds: float,
    batch_limit: int,
    scan_interval: float,
    idempotency_key: str,
    job_type: str,
    auto_reschedule: bool = True,
    now_factory: Callable[[], datetime] = datetime.utcnow,
) -> QueueJobDTO:
    delay = max(0.0, float(delay_seconds))
    available_at = now_factory() + timedelta(seconds=delay)
    payload = {
        "batch_limit": int(batch_limit),
        "scan_interval": float(scan_interval),
        "idempotency_key": idempotency_key,
        "auto_reschedule": bool(auto_reschedule),
    }
    return await asyncio.to_thread(
        persistence.enqueue,
        job_type,
        payload,
        available_at=available_at,
        idempotency_key=idempotency_key,
    )


class MetadataService(Protocol):
    async def enqueue(
        self,
        download_id: int,
        file_path: Path,
        *,
        payload: Mapping[str, Any] | None,
        request_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]: ...


class ArtworkService(Protocol):
    async def enqueue(
        self,
        download_id: int,
        file_path: str,
        *,
        metadata: Mapping[str, Any],
        spotify_track_id: str | None,
        spotify_album_id: str | None,
        artwork_url: str | None,
    ) -> Any: ...


class LyricsService(Protocol):
    async def enqueue(
        self,
        download_id: int,
        file_path: str,
        track_info: Mapping[str, Any],
    ) -> Any: ...


class ArtistCacheService(Protocol):
    async def update_hint(
        self,
        *,
        artist_id: str,
        hint: ArtistCacheHint | None,
    ) -> None: ...

    async def evict_artist(self, *, artist_id: str) -> None: ...


class SyncJobSubmitter(Protocol):
    async def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        priority: int | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any] | None: ...


@dataclass(slots=True)
class MatchingHandlerDeps:
    """Dependencies required by the matching orchestrator handler."""

    engine: MusicMatchingEngine
    session_factory: Callable[[], AbstractContextManager[Session]] = session_scope
    confidence_threshold: float = field(
        default_factory=lambda: load_matching_confidence_threshold()
    )
    external_timeout_ms: int = field(
        default_factory=lambda: _resolve_timeout_ms(os.getenv("EXTERNAL_TIMEOUT_MS"))
    )


class MatchingJobError(Exception):
    """Raised when a matching job cannot be completed successfully."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        retry: bool,
        retry_in: int | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.retry = retry
        self.retry_in = retry_in


def load_matching_confidence_threshold(
    *,
    setting_key: str = "matching_confidence_threshold",
    env_key: str = "MATCHING_CONFIDENCE_THRESHOLD",
    default: float = 0.65,
) -> float:
    from app.utils.settings_store import read_setting

    setting_value = read_setting(setting_key)
    env_value = os.getenv(env_key)
    for raw in (setting_value, env_value):
        if not raw:
            continue
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            continue
        if 0 < parsed <= 1:
            return parsed
    return default


async def handle_matching(
    job: QueueJobDTO,
    deps: MatchingHandlerDeps,
) -> Mapping[str, Any]:
    """Process a matching job and persist qualifying candidates."""

    payload = dict(job.payload or {})
    job_type = str(payload.get("type") or job.type or "matching")
    spotify_track = payload.get("spotify_track")
    candidates = payload.get("candidates")

    if not isinstance(spotify_track, Mapping) or not spotify_track:
        raise MatchingJobError(
            "invalid_payload",
            "Matching job missing spotify_track payload",
            retry=False,
        )
    if (
        not isinstance(candidates, Sequence)
        or isinstance(candidates, (str, bytes))
        or not candidates
    ):
        raise MatchingJobError(
            "invalid_payload",
            "Matching job missing candidates",
            retry=False,
        )

    spotify_track_dto = normalize_spotify_track(spotify_track)
    qualifying: list[tuple[dict[str, Any], float]] = []
    discarded = 0
    scores: list[float] = []

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            discarded += 1
            continue
        candidate_mapping = dict(candidate)
        candidate_dto = normalize_slskd_candidate(candidate_mapping)
        score = await _invoke_with_timeout(
            asyncio.to_thread(
                deps.engine.calculate_slskd_match_confidence,
                spotify_track_dto,
                candidate_dto,
            ),
            deps.external_timeout_ms,
        )
        if score >= deps.confidence_threshold:
            qualifying.append((candidate_mapping, float(score)))
            scores.append(float(score))
        else:
            discarded += 1

    if not qualifying:
        raise MatchingJobError(
            "no_match",
            "No candidates met the configured confidence threshold",
            retry=False,
        )

    qualifying.sort(key=lambda item: item[1], reverse=True)

    spotify_track_id = str(spotify_track.get("id") or "")

    def _persist_matches(session: Session) -> int:
        stored_local = 0
        for candidate, score in qualifying:
            match = Match(
                source=job_type,
                spotify_track_id=spotify_track_id or None,
                target_id=str(candidate.get("id")) if candidate.get("id") else None,
                confidence=float(score),
            )
            session.add(match)
            stored_local += 1
        return stored_local

    stored = await run_session(_persist_matches, factory=deps.session_factory)

    average_confidence = statistics.mean(scores) if scores else 0.0
    rounded_average = round(average_confidence, 4)

    from app.utils.settings_store import increment_counter, write_setting

    write_setting("metrics.matching.last_average_confidence", f"{rounded_average:.4f}")
    write_setting("metrics.matching.last_discarded", str(discarded))
    increment_counter("metrics.matching.discarded_total", amount=discarded)
    increment_counter("metrics.matching.saved_total", amount=stored)

    record_activity(
        "metadata",
        "matching_batch",
        details={
            "job_id": job.id,
            "job_type": job_type,
            "batch_size": 1,
            "stored": stored,
            "discarded": discarded,
            "average_confidence": rounded_average,
        },
    )

    return {
        "job_type": job_type,
        "spotify_track_id": spotify_track_id or None,
        "stored": stored,
        "discarded": discarded,
        "average_confidence": rounded_average,
        "matches": [
            {"candidate": candidate, "score": round(score, 4)} for candidate, score in qualifying
        ],
    }


def build_matching_handler(
    deps: MatchingHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    """Return a dispatcher-compatible handler bound to matching dependencies."""

    async def _handler(job: QueueJobDTO) -> Mapping[str, Any]:
        return await handle_matching(job, deps)

    return _handler


@dataclass(slots=True)
class SyncHandlerDeps:
    """Bundle dependencies required by the sync orchestrator handler."""

    soulseek_client: SoulseekClient
    session_factory: Callable[[], AbstractContextManager[Session]] = session_scope
    retry_policy_provider: RetryPolicyProvider | None = None
    rng: random.Random = field(default_factory=random.Random)
    metadata_service: MetadataService | None = None
    artwork_service: ArtworkService | None = None
    lyrics_service: LyricsService | None = None
    music_dir: Path = field(
        default_factory=lambda: Path(os.getenv("MUSIC_DIR", "./music")).expanduser()
    )
    external_timeout_ms: int = field(
        default_factory=lambda: _resolve_timeout_ms(os.getenv("EXTERNAL_TIMEOUT_MS"))
    )
    retry_job_type: str = "sync"
    retry_policy_override: InitVar[SyncRetryPolicy | None] = None
    _retry_policy_override: SyncRetryPolicy | None = field(
        init=False, default=None, repr=False
    )

    def __post_init__(
        self, retry_policy_override: SyncRetryPolicy | None
    ) -> None:
        self._retry_policy_override = retry_policy_override
        if self.retry_policy_provider is None:
            self.retry_policy_provider = get_retry_policy_provider()
        if not self.retry_job_type:
            self.retry_job_type = "sync"

    def get_retry_policy(
        self, *, job_type: str | None = None, force_reload: bool = False
    ) -> SyncRetryPolicy:
        if self._retry_policy_override is not None and not force_reload:
            return self._retry_policy_override

        provider = self.retry_policy_provider or get_retry_policy_provider()
        self.retry_policy_provider = provider
        resolved_job_type = job_type or self.retry_job_type or "sync"
        if force_reload:
            provider.invalidate(resolved_job_type)
            self._retry_policy_override = None
        return provider.get_retry_policy(resolved_job_type)

    @property
    def retry_policy(self) -> SyncRetryPolicy:
        return self.get_retry_policy()


@dataclass(slots=True)
class RetryHandlerDeps:
    """Dependencies required by the orchestrated retry handler."""

    session_factory: Callable[[], AbstractContextManager[Session]] = session_scope
    submit_sync_job: SyncJobSubmitter = enqueue_sync_job
    retry_policy: SyncRetryPolicy = field(
        default_factory=lambda: load_sync_retry_policy(job_type="retry")
    )
    rng: random.Random = field(default_factory=random.Random)
    batch_limit: int = field(
        default_factory=lambda: _safe_int(
            os.getenv("RETRY_SCAN_BATCH_LIMIT"), _RETRY_DEFAULT_BATCH_LIMIT
        )
    )
    scan_interval: float = field(
        default_factory=lambda: _safe_float(
            os.getenv("RETRY_SCAN_INTERVAL_SEC"), _RETRY_DEFAULT_SCAN_INTERVAL
        )
    )
    external_timeout_ms: int = field(
        default_factory=lambda: _resolve_timeout_ms(os.getenv("EXTERNAL_TIMEOUT_MS"))
    )
    now_factory: Callable[[], datetime] = datetime.utcnow
    retry_job_type: str = "retry"
    retry_job_idempotency_key: str = "retry-scan"
    auto_reschedule: bool = True

    def __post_init__(self) -> None:
        self.batch_limit = _coerce_positive_int(self.batch_limit, _RETRY_DEFAULT_BATCH_LIMIT)
        self.scan_interval = _coerce_positive_float(
            self.scan_interval, _RETRY_DEFAULT_SCAN_INTERVAL
        )
        self.external_timeout_ms = max(1_000, int(self.external_timeout_ms))
        if not self.retry_job_type:
            self.retry_job_type = "retry"
        if not self.retry_job_idempotency_key:
            self.retry_job_idempotency_key = "retry-scan"


@dataclass(slots=True)
class ArtistRefreshHandlerDeps:
    """Dependencies required to enqueue artist delta jobs from refresh work."""

    config: WatchlistWorkerConfig
    dao: WatchlistDAO = field(default_factory=WatchlistDAO)
    submit_delta_job: SyncJobSubmitter = enqueue_artist_delta_job
    now_factory: Callable[[], datetime] = datetime.utcnow
    delta_priority: int = field(
        default_factory=lambda: settings.orchestrator.priority_map.get("artist_delta", 0)
    )
    refresh_priority: int = field(
        default_factory=lambda: settings.orchestrator.priority_map.get("artist_refresh", 0)
    )
    cache_service: ArtistCacheService | None = None
    retry_budget: int = field(init=False)
    cooldown_minutes: int = field(init=False)

    def __post_init__(self) -> None:
        self.delta_priority = _coerce_priority(self.delta_priority)
        self.refresh_priority = _coerce_priority(self.refresh_priority)
        self.retry_budget = max(1, int(self.config.retry_budget_per_artist))
        self.cooldown_minutes = max(0, int(self.config.cooldown_minutes))


@dataclass(slots=True)
class ArtistDeltaHandlerDeps:
    """Dependencies required by the watchlist orchestrator handler."""

    spotify_client: SpotifyClient
    soulseek_client: SoulseekClient
    config: WatchlistWorkerConfig
    dao: WatchlistDAO = field(default_factory=WatchlistDAO)
    submit_sync_job: SyncJobSubmitter = enqueue_sync_job
    rng: random.Random = field(default_factory=random.Random)
    now_factory: Callable[[], datetime] = datetime.utcnow
    cache_service: ArtistCacheService | None = None
    external_timeout_ms: int = field(
        default_factory=lambda: _resolve_timeout_ms(os.getenv("EXTERNAL_TIMEOUT_MS"))
    )
    db_mode: str = field(init=False)
    spotify_timeout_ms: int = field(init=False)
    search_timeout_ms: int = field(init=False)
    retry_budget: int = field(init=False)
    cooldown_minutes: int = field(init=False)
    backoff_base_ms: int = field(init=False)
    jitter_pct: float = field(init=False)
    retry_max: int = field(init=False)

    def __post_init__(self) -> None:
        mode = (self.config.db_io_mode or "thread").strip().lower()
        self.db_mode = "async" if mode == "async" else "thread"
        timeout_cap = max(1, int(self.external_timeout_ms))
        self.spotify_timeout_ms = min(timeout_cap, max(1, int(self.config.spotify_timeout_ms)))
        self.search_timeout_ms = min(timeout_cap, max(1, int(self.config.slskd_search_timeout_ms)))
        self.retry_budget = max(1, int(self.config.retry_budget_per_artist))
        self.cooldown_minutes = max(0, int(self.config.cooldown_minutes))
        self.backoff_base_ms = max(0, int(self.config.backoff_base_ms))
        self.jitter_pct = max(0.0, float(self.config.jitter_pct))
        self.retry_max = max(1, int(self.config.retry_max))


WatchlistHandlerDeps = ArtistDeltaHandlerDeps


class WatchlistProcessingError(Exception):
    """Raised when watchlist artist processing fails."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _calculate_artist_backoff_ms(attempt: int, deps: ArtistDeltaHandlerDeps) -> int:
    base = deps.backoff_base_ms
    exponent = max(int(attempt) - 1, 0)
    delay = base * (2**exponent)
    if delay <= 0:
        return 0
    if deps.jitter_pct > 0:
        spread = delay * deps.jitter_pct
        delay += deps.rng.uniform(-spread, spread)
    return min(max(int(delay), 0), _WATCHLIST_MAX_BACKOFF_MS)


def _artist_cooldown_until(deps: ArtistDeltaHandlerDeps) -> datetime:
    now = deps.now_factory()
    if deps.cooldown_minutes <= 0:
        return now
    return now + timedelta(minutes=deps.cooldown_minutes)


async def _call_watchlist_dao(
    deps: ArtistDeltaHandlerDeps, method_name: str, /, *args, **kwargs
):
    method = getattr(deps.dao, method_name)
    if deps.db_mode == "thread":
        return await asyncio.to_thread(method, *args, **kwargs)
    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _build_search_query(artist_name: str, album: Mapping[str, Any], track: Mapping[str, Any]) -> str:
    parts: list[str] = []
    candidate_artist = artist_name or _primary_artist_name(track, album)
    if candidate_artist:
        parts.append(candidate_artist.strip())
    title = track.get("name") or track.get("title")
    if title:
        parts.append(str(title).strip())
    album_name = album.get("name")
    if album_name:
        parts.append(str(album_name).strip())
    return " ".join(part for part in parts if part)


def _primary_artist_name(track: Mapping[str, Any], album: Mapping[str, Any]) -> str:
    def _extract_artist(collection: Iterable[Mapping[str, Any]] | None) -> str:
        if not collection:
            return ""
        for artist in collection:
            if isinstance(artist, Mapping) and artist.get("name"):
                return str(artist["name"])
        return ""

    artists = track.get("artists") if isinstance(track.get("artists"), list) else None
    name = _extract_artist(artists)
    if name:
        return name
    album_artists = album.get("artists") if isinstance(album.get("artists"), list) else None
    return _extract_artist(album_artists)


def _select_candidate(result: Any) -> tuple[str | None, Mapping[str, Any] | None]:
    if isinstance(result, Mapping):
        entries = result.get("results")
        if isinstance(entries, list):
            for entry in entries:
                username, file_info = _extract_candidate(entry)
                if username and file_info:
                    return username, file_info
    elif isinstance(result, list):
        for entry in result:
            username, file_info = _extract_candidate(entry)
            if username and file_info:
                return username, file_info
    return None, None


def _extract_candidate(candidate: Any) -> tuple[str | None, Mapping[str, Any] | None]:
    if not isinstance(candidate, Mapping):
        return None, None
    username = candidate.get("username")
    files = candidate.get("files")
    if isinstance(files, list):
        for entry in files:
            if not isinstance(entry, Mapping):
                continue
            if not entry.get("filename") and not entry.get("name"):
                continue
            return str(username) if username else None, entry
    if isinstance(candidate.get("filename"), str) or isinstance(candidate.get("name"), str):
        return str(username) if username else None, candidate
    return None, None


def _extract_priority(payload: Mapping[str, Any]) -> int:
    return int(payload.get("priority") or payload.get("prio") or 0)


def _build_album_payload(candidate: ArtistTrackCandidate) -> Mapping[str, Any]:
    album = candidate.release.album
    payload: dict[str, Any] = {
        "id": album.source_id or "",
        "name": album.title,
        "artists": [
            {"name": artist.name}
            for artist in getattr(album, "artists", ())
            if getattr(artist, "name", None)
        ],
    }
    if candidate.release.raw is not None:
        payload.setdefault("metadata", dict(candidate.release.raw))
    return payload


def _build_track_payload(candidate: ArtistTrackCandidate) -> Mapping[str, Any]:
    track = candidate.track
    artists = [
        {"name": artist.name}
        for artist in getattr(track, "artists", ())
        if getattr(artist, "name", None)
    ]
    payload: dict[str, Any] = {
        "id": track.source_id or "",
        "name": track.title,
        "artists": artists,
    }
    if track.album is not None:
        payload.setdefault(
            "album",
            {
                "id": track.album.source_id or "",
                "name": track.album.title,
            },
        )
    return payload


@dataclass(slots=True)
class _DownloadJobSpec:
    download_id: int
    username: str
    job_payload: dict[str, Any]
    priority: int
    idempotency_key: str
    track_id: str


async def _fetch_artist_candidates(
    artist: WatchlistArtistRow, deps: ArtistDeltaHandlerDeps
) -> list[ArtistTrackCandidate]:
    started = time.perf_counter()
    try:
        albums = await _invoke_with_timeout(
            asyncio.to_thread(
                deps.spotify_client.get_artist_albums,
                artist.spotify_artist_id,
            ),
            deps.spotify_timeout_ms,
        )
    except asyncio.TimeoutError as exc:
        log_event(
            logger,
            "artist.fetch",
            component=_WATCHLIST_LOG_COMPONENT,
            status="error",
            entity_id=artist.spotify_artist_id,
            error="spotify_timeout",
        )
        raise WatchlistProcessingError(
            "timeout",
            f"spotify albums timeout for {artist.spotify_artist_id}",
            retryable=True,
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        log_event(
            logger,
            "artist.fetch",
            component=_WATCHLIST_LOG_COMPONENT,
            status="error",
            entity_id=artist.spotify_artist_id,
            error="spotify_failure",
        )
        raise WatchlistProcessingError(
            "dependency_error",
            f"spotify albums failed: {exc}",
            retryable=True,
        ) from exc

    album_list: list[Mapping[str, Any]] = []
    if isinstance(albums, list):
        album_list = [album for album in albums if isinstance(album, Mapping)]
    elif isinstance(albums, Iterable):
        album_list = [album for album in albums if isinstance(album, Mapping)]

    releases = [
        release
        for album in album_list
        for release in [AlbumRelease.from_mapping(album, source="spotify")]
        if release is not None
    ]
    recent_releases = filter_new_releases(releases, last_checked=artist.last_checked)
    track_candidates: list[ArtistTrackCandidate] = []

    for release in recent_releases:
        album_id = release.album_id or ""
        if not album_id:
            continue
        try:
            tracks = await _invoke_with_timeout(
                asyncio.to_thread(deps.spotify_client.get_album_tracks, album_id),
                deps.spotify_timeout_ms,
            )
        except asyncio.TimeoutError as exc:
            log_event(
                logger,
                "artist.fetch",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="spotify_timeout",
                album_id=album_id,
            )
            raise WatchlistProcessingError(
                "timeout",
                f"spotify tracks timeout for album {album_id}",
                retryable=True,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            log_event(
                logger,
                "artist.fetch",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="spotify_failure",
                album_id=album_id,
            )
            raise WatchlistProcessingError(
                "dependency_error",
                f"spotify album tracks failed: {exc}",
                retryable=True,
            ) from exc

        track_list: list[Mapping[str, Any]] = []
        if isinstance(tracks, list):
            track_list = [track for track in tracks if isinstance(track, Mapping)]
        elif isinstance(tracks, Iterable):
            track_list = [track for track in tracks if isinstance(track, Mapping)]
        for track in track_list:
            candidate = ArtistTrackCandidate.from_mapping(track, release, source="spotify")
            if candidate is not None:
                track_candidates.append(candidate)

    duration_ms = int((time.perf_counter() - started) * 1000)
    status = "ok" if track_candidates else "noop"
    log_event(
        logger,
        "artist.fetch",
        component=_WATCHLIST_LOG_COMPONENT,
        status=status,
        entity_id=artist.spotify_artist_id,
        album_count=len(album_list),
        release_count=len(recent_releases),
        track_count=len(track_candidates),
        duration_ms=duration_ms,
    )
    return track_candidates


async def _compute_artist_delta(
    artist: WatchlistArtistRow,
    candidates: Sequence[ArtistTrackCandidate],
    deps: ArtistDeltaHandlerDeps,
) -> ArtistDelta | None:
    if not candidates:
        log_event(
            logger,
            "artist.delta",
            component=_WATCHLIST_LOG_COMPONENT,
            status="noop",
            entity_id=artist.spotify_artist_id,
            new_count=0,
            updated_count=0,
            known_count=0,
        )
        if deps.cache_service is not None:
            await deps.cache_service.update_hint(artist_id=artist.spotify_artist_id, hint=None)
        return None

    track_ids = [candidate.track_id for candidate in candidates if candidate.track_id]
    existing: set[str] = set()
    if track_ids:
        fetched = await _call_watchlist_dao(deps, "load_existing_track_ids", track_ids)
        if fetched:
            existing = {str(item) for item in fetched}

    delta = build_artist_delta(
        candidates,
        existing,
        last_checked=artist.last_checked,
    )
    new_count = len(delta.new)
    updated_count = len(delta.updated)
    status = "ok" if (new_count or updated_count) else "noop"
    fields: dict[str, Any] = {
        "component": _WATCHLIST_LOG_COMPONENT,
        "status": status,
        "entity_id": artist.spotify_artist_id,
        "new_count": new_count,
        "updated_count": updated_count,
        "known_count": len(existing),
    }
    if delta.cache_hint is not None:
        fields["cache_etag"] = delta.cache_hint.etag
        fields["release_count"] = delta.cache_hint.release_count
        if delta.cache_hint.latest_release_at:
            fields["latest_release_at"] = delta.cache_hint.latest_release_at.isoformat()
    log_event(logger, "artist.delta", **fields)
    if deps.cache_service is not None:
        await deps.cache_service.update_hint(
            artist_id=artist.spotify_artist_id,
            hint=delta.cache_hint,
        )
    return delta


async def _persist_candidates(
    artist: WatchlistArtistRow,
    candidates: Sequence[ArtistTrackCandidate],
    deps: ArtistDeltaHandlerDeps,
) -> tuple[list[_DownloadJobSpec], dict[str, int]]:
    if not candidates:
        log_event(
            logger,
            "artist.persist",
            component=_WATCHLIST_LOG_COMPONENT,
            status="noop",
            entity_id=artist.spotify_artist_id,
            created=0,
            attempts=0,
            duration_ms=0,
            search_attempts=0,
            search_misses=0,
        )
        return [], {"search_attempts": 0, "search_misses": 0}

    started = time.perf_counter()
    jobs: list[_DownloadJobSpec] = []
    search_attempts = 0
    search_misses = 0

    for candidate in candidates:
        album_payload = _build_album_payload(candidate)
        track_payload = _build_track_payload(candidate)
        query = _build_search_query(artist.name, album_payload, track_payload)
        if not query:
            search_misses += 1
            continue
        search_attempts += 1
        try:
            results = await _invoke_with_timeout(
                deps.soulseek_client.search(query),
                deps.search_timeout_ms,
            )
        except asyncio.TimeoutError as exc:
            log_event(
                logger,
                "artist.enqueue",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="search_timeout",
                query=query,
            )
            raise WatchlistProcessingError(
                "timeout", f"search timeout for {query}", retryable=True
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            log_event(
                logger,
                "artist.enqueue",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="search_failure",
                query=query,
            )
            raise WatchlistProcessingError(
                "dependency_error",
                f"search failed for {query}: {exc}",
                retryable=True,
            ) from exc

        username, file_info = _select_candidate(results)
        if not username or not file_info:
            search_misses += 1
            continue

        payload = dict(file_info)
        filename = str(
            payload.get("filename")
            or payload.get("name")
            or track_payload.get("name")
            or "unknown"
        )
        priority = _extract_priority(payload)
        track_id = str(track_payload.get("id") or "").strip()
        album_id = str(album_payload.get("id") or "").strip()

        download_id = await _call_watchlist_dao(
            deps,
            "create_download_record",
            username=username,
            filename=filename,
            priority=priority,
            spotify_track_id=track_id,
            spotify_album_id=album_id,
            payload=payload,
        )
        if download_id is None:
            log_event(
                logger,
                "artist.persist",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="persist_failed",
                filename=filename,
            )
            raise WatchlistProcessingError(
                "internal_error",
                f"failed to persist download for {filename}",
                retryable=False,
            )

        payload = dict(payload)
        payload["download_id"] = int(download_id)
        payload.setdefault("filename", filename)
        payload["priority"] = priority

        idempotency_key = f"watchlist-download:{download_id}"
        job_payload = {
            "username": username,
            "files": [payload],
            "priority": priority,
            "source": "watchlist",
            "idempotency_key": idempotency_key,
        }

        jobs.append(
            _DownloadJobSpec(
                download_id=int(download_id),
                username=username,
                job_payload=job_payload,
                priority=priority,
                idempotency_key=idempotency_key,
                track_id=track_id,
            )
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    status = "ok" if jobs else "noop"
    log_event(
        logger,
        "artist.persist",
        component=_WATCHLIST_LOG_COMPONENT,
        status=status,
        entity_id=artist.spotify_artist_id,
        created=len(jobs),
        attempts=len(candidates),
        search_attempts=search_attempts,
        search_misses=search_misses,
        duration_ms=duration_ms,
    )
    return jobs, {"search_attempts": search_attempts, "search_misses": search_misses}


async def _submit_with_retry(
    submitter: SyncJobSubmitter,
    payload: Mapping[str, Any],
    *,
    priority: int,
    idempotency_key: str,
    retries: int = 3,
) -> Mapping[str, Any] | None:
    attempt = 0
    while True:
        attempt += 1
        try:
            return await submitter(
                payload,
                priority=priority,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            if attempt >= max(1, retries):
                raise
            await asyncio.sleep(0)


async def _enqueue_downloads(
    artist: WatchlistArtistRow,
    jobs: Sequence[_DownloadJobSpec],
    deps: ArtistDeltaHandlerDeps,
    *,
    metrics: Mapping[str, int],
) -> int:
    search_attempts = int(metrics.get("search_attempts", 0))
    search_misses = int(metrics.get("search_misses", 0))
    if not jobs:
        log_event(
            logger,
            "artist.enqueue",
            component=_WATCHLIST_LOG_COMPONENT,
            status="noop",
            entity_id=artist.spotify_artist_id,
            queued=0,
            search_attempts=search_attempts,
            search_misses=search_misses,
            duration_ms=0,
        )
        return 0

    started = time.perf_counter()
    queued = 0
    for job in jobs:
        try:
            await _submit_with_retry(
                deps.submit_sync_job,
                job.job_payload,
                priority=job.priority,
                idempotency_key=job.idempotency_key,
            )
        except IntegrityError as exc:
            await _call_watchlist_dao(
                deps,
                "mark_download_failed",
                int(job.download_id),
                "integrity_error",
            )
            log_event(
                logger,
                "artist.enqueue",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="integrity_error",
                download_id=job.download_id,
            )
            raise WatchlistProcessingError(
                "dependency_error",
                f"failed to enqueue download {job.download_id}: {exc}",
                retryable=True,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            await _call_watchlist_dao(
                deps,
                "mark_download_failed",
                int(job.download_id),
                str(exc),
            )
            log_event(
                logger,
                "artist.enqueue",
                component=_WATCHLIST_LOG_COMPONENT,
                status="error",
                entity_id=artist.spotify_artist_id,
                error="enqueue_failed",
                download_id=job.download_id,
            )
            raise WatchlistProcessingError(
                "dependency_error",
                f"failed to enqueue download {job.download_id}: {exc}",
                retryable=True,
            ) from exc
        else:
            queued += 1

    duration_ms = int((time.perf_counter() - started) * 1000)
    log_event(
        logger,
        "artist.enqueue",
        component=_WATCHLIST_LOG_COMPONENT,
        status="ok" if queued else "noop",
        entity_id=artist.spotify_artist_id,
        queued=queued,
        search_attempts=search_attempts,
        search_misses=search_misses,
        duration_ms=duration_ms,
    )
    return queued


async def artist_refresh(
    job: QueueJobDTO, deps: ArtistRefreshHandlerDeps
) -> Mapping[str, Any]:
    payload = dict(job.payload or {})
    artist_id_raw = payload.get("artist_id")
    if artist_id_raw is None:
        raise MatchingJobError("invalid_payload", "missing artist_id", retry=False)

    try:
        artist_pk = int(artist_id_raw)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive logging
        raise MatchingJobError("invalid_payload", "invalid artist_id", retry=False) from exc

    artist = await asyncio.to_thread(deps.dao.get_artist, artist_pk)
    attempts = int(job.attempts or 0)
    if artist is None:
        log_event(
            logger,
            "artist.watch",
            component=_ARTIST_REFRESH_LOG_COMPONENT,
            status="missing",
            artist_id=artist_pk,
            attempts=attempts,
        )
        return {
            "status": "missing",
            "artist_id": artist_pk,
            "attempts": attempts,
        }

    now = deps.now_factory()
    if artist.retry_block_until and artist.retry_block_until > now:
        log_event(
            logger,
            "artist.watch",
            component=_ARTIST_REFRESH_LOG_COMPONENT,
            status="cooldown",
            entity_id=artist.spotify_artist_id,
            attempts=attempts,
            retry_block_until=artist.retry_block_until.isoformat(),
        )
        return {
            "status": "cooldown",
            "artist_id": artist.spotify_artist_id,
            "attempts": attempts,
            "retry_block_until": artist.retry_block_until.isoformat(),
        }

    cutoff = _parse_iso_datetime(payload.get("cutoff"))
    if cutoff and artist.last_checked and artist.last_checked > cutoff:
        log_event(
            logger,
            "artist.watch",
            component=_ARTIST_REFRESH_LOG_COMPONENT,
            status="noop",
            entity_id=artist.spotify_artist_id,
            attempts=attempts,
            reason="stale",
        )
        return {
            "status": "noop",
            "artist_id": artist.spotify_artist_id,
            "attempts": attempts,
            "reason": "stale",
        }

    delta_payload: dict[str, Any] = {"artist_id": artist_pk}
    if cutoff:
        delta_payload["cutoff"] = cutoff.isoformat()
    delta_idempotency = payload.get("delta_idempotency")
    if not delta_idempotency:
        cutoff_token = cutoff.isoformat() if cutoff else "never"
        delta_idempotency = f"artist-delta:{artist_pk}:{cutoff_token}"

    priority = deps.delta_priority
    try:
        await _submit_with_retry(
            deps.submit_delta_job,
            delta_payload,
            priority=priority,
            idempotency_key=delta_idempotency,
        )
    except IntegrityError as exc:
        log_event(
            logger,
            "artist.watch",
            component=_ARTIST_REFRESH_LOG_COMPONENT,
            status="error",
            entity_id=artist.spotify_artist_id,
            error="delta_enqueue_failed",
        )
        raise MatchingJobError(
            "delta_enqueue_failed",
            f"failed to enqueue artist delta for {artist.spotify_artist_id}",
            retry=True,
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        log_event(
            logger,
            "artist.watch",
            component=_ARTIST_REFRESH_LOG_COMPONENT,
            status="error",
            entity_id=artist.spotify_artist_id,
            error="delta_enqueue_failed",
        )
        raise MatchingJobError(
            "delta_enqueue_failed",
            f"failed to enqueue artist delta for {artist.spotify_artist_id}",
            retry=True,
        ) from exc

    if deps.cache_service is not None:
        await deps.cache_service.evict_artist(artist_id=artist.spotify_artist_id)

    log_event(
        logger,
        "artist.watch",
        component=_ARTIST_REFRESH_LOG_COMPONENT,
        status="queued",
        entity_id=artist.spotify_artist_id,
        attempts=attempts,
        delta_idempotency=delta_idempotency,
        delta_priority=priority,
    )
    return {
        "status": "enqueued",
        "artist_id": artist.spotify_artist_id,
        "attempts": attempts,
        "delta_idempotency_key": delta_idempotency,
        "delta_priority": priority,
    }


async def artist_delta(
    job: QueueJobDTO, deps: ArtistDeltaHandlerDeps
) -> Mapping[str, Any]:
    payload = dict(job.payload or {})
    artist_id_raw = payload.get("artist_id")
    if artist_id_raw is None:
        raise MatchingJobError("invalid_payload", "missing artist_id", retry=False)
    try:
        artist_pk = int(artist_id_raw)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive logging
        raise MatchingJobError("invalid_payload", "invalid artist_id", retry=False) from exc

    artist = await _call_watchlist_dao(deps, "get_artist", artist_pk)
    attempts = max(int(job.attempts or 0), 1)
    if artist is None:
        log_event(
            logger,
            "artist.watch",
            component=_WATCHLIST_LOG_COMPONENT,
            status="missing",
            artist_id=artist_pk,
            attempts=attempts,
        )
        return {
            "status": "missing",
            "artist_id": artist_pk,
            "queued": 0,
            "attempts": attempts,
        }

    now = deps.now_factory()
    if artist.retry_block_until and artist.retry_block_until > now:
        log_event(
            logger,
            "artist.watch",
            component=_WATCHLIST_LOG_COMPONENT,
            status="cooldown",
            entity_id=artist.spotify_artist_id,
            attempts=attempts,
            retry_block_until=artist.retry_block_until.isoformat(),
        )
        return {
            "status": "cooldown",
            "artist_id": artist.spotify_artist_id,
            "queued": 0,
            "attempts": attempts,
            "retry_block_until": artist.retry_block_until.isoformat(),
        }

    cutoff = _parse_iso_datetime(payload.get("cutoff"))
    if cutoff and artist.last_checked and artist.last_checked > cutoff:
        log_event(
            logger,
            "artist.watch",
            component=_WATCHLIST_LOG_COMPONENT,
            status="noop",
            entity_id=artist.spotify_artist_id,
            attempts=attempts,
            reason="stale",
        )
        return {
            "status": "noop",
            "artist_id": artist.spotify_artist_id,
            "queued": 0,
            "attempts": attempts,
            "reason": "stale",
        }

    start = time.perf_counter()
    try:
        candidates = await _fetch_artist_candidates(artist, deps)
        delta = await _compute_artist_delta(artist, candidates, deps)
        if delta is None or (not delta.new and not delta.updated):
            await _call_watchlist_dao(
                deps,
                "mark_success",
                artist.id,
                checked_at=deps.now_factory(),
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_event(
                logger,
                "artist.watch",
                component=_WATCHLIST_LOG_COMPONENT,
                status="noop",
                entity_id=artist.spotify_artist_id,
                attempts=attempts,
                duration_ms=duration_ms,
                queued=0,
            )
            return {
                "status": "noop",
                "artist_id": artist.spotify_artist_id,
                "queued": 0,
                "attempts": attempts,
                "duration_ms": duration_ms,
            }

        pending_candidates = list(delta.new) + list(delta.updated)
        jobs, metrics = await _persist_candidates(artist, pending_candidates, deps)
        queued = await _enqueue_downloads(
            artist,
            jobs,
            deps,
            metrics=metrics,
        )
    except WatchlistProcessingError as exc:
        if not exc.retryable:
            await _call_watchlist_dao(
                deps,
                "mark_failed",
                artist.id,
                reason=exc.code,
                retry_at=deps.now_factory(),
                retry_block_until=_artist_cooldown_until(deps),
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_event(
                logger,
                "artist.watch",
                component=_WATCHLIST_LOG_COMPONENT,
                status="failed",
                entity_id=artist.spotify_artist_id,
                attempts=attempts,
                duration_ms=duration_ms,
                error=exc.code,
            )
            raise MatchingJobError(exc.code, str(exc), retry=False) from exc

        backoff_ms = _calculate_artist_backoff_ms(attempts, deps)
        retry_seconds = max(1, backoff_ms // 1000)
        retry_at = deps.now_factory() + timedelta(seconds=retry_seconds)
        await _call_watchlist_dao(
            deps,
            "mark_failed",
            artist.id,
            reason=exc.code,
            retry_at=retry_at,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_event(
            logger,
            "artist.watch",
            component=_WATCHLIST_LOG_COMPONENT,
            status="retry",
            entity_id=artist.spotify_artist_id,
            attempts=attempts,
            duration_ms=duration_ms,
            retry_in=retry_seconds,
            error=exc.code,
        )
        raise MatchingJobError(exc.code, str(exc), retry=True, retry_in=retry_seconds) from exc

    await _call_watchlist_dao(
        deps,
        "mark_success",
        artist.id,
        checked_at=deps.now_factory(),
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    status = "ok" if queued else "noop"
    log_event(
        logger,
        "artist.watch",
        component=_WATCHLIST_LOG_COMPONENT,
        status=status,
        entity_id=artist.spotify_artist_id,
        attempts=attempts,
        duration_ms=duration_ms,
        queued=queued,
    )
    return {
        "status": status,
        "artist_id": artist.spotify_artist_id,
        "queued": queued,
        "attempts": attempts,
        "duration_ms": duration_ms,
    }


async def handle_artist_refresh(
    job: QueueJobDTO, deps: ArtistRefreshHandlerDeps
) -> Mapping[str, Any]:
    return await artist_refresh(job, deps)


async def handle_artist_delta(
    job: QueueJobDTO, deps: ArtistDeltaHandlerDeps
) -> Mapping[str, Any]:
    return await artist_delta(job, deps)


def build_artist_refresh_handler(
    deps: ArtistRefreshHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    async def _handler(job: QueueJobDTO) -> Mapping[str, Any]:
        return await artist_refresh(job, deps)

    return _handler


def build_artist_delta_handler(
    deps: ArtistDeltaHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    async def _handler(job: QueueJobDTO) -> Mapping[str, Any]:
        return await artist_delta(job, deps)

    return _handler


def build_watchlist_handler(
    deps: ArtistDeltaHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    return build_artist_delta_handler(deps)


handle_watchlist = handle_artist_delta


@dataclass(slots=True)
class _RetryCandidate:
    download_id: int
    retry_count: int
    username: str
    job_payload: dict[str, Any]
    priority: int
    idempotency_key: str


async def _invoke_with_timeout(
    coro: Awaitable[Any], timeout_ms: int
) -> Any:  # pragma: no cover - thin wrapper
    timeout_seconds = max(0.001, timeout_ms / 1000)
    return await asyncio.wait_for(coro, timeout=timeout_seconds)


def _extract_download_id(candidate: Any) -> int | None:
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _filter_active_files(
    job_files: Iterable[Mapping[str, Any]],
    *,
    session: Session,
) -> list[MutableMapping[str, Any]]:
    filtered: list[MutableMapping[str, Any]] = []
    for file_info in job_files:
        identifier = file_info.get("download_id") or file_info.get("id")
        download_id = _extract_download_id(identifier)
        if download_id is None:
            continue
        record = session.get(Download, download_id)
        if record is None or record.state == "dead_letter":
            continue
        filtered.append(dict(file_info))
    return filtered


def _mark_downloading(
    session: Session,
    downloads: Iterable[MutableMapping[str, Any]],
) -> None:
    now = datetime.utcnow()
    for file_info in downloads:
        identifier = file_info.get("download_id") or file_info.get("id")
        download_id = _extract_download_id(identifier)
        if download_id is None:
            continue
        download = session.get(Download, download_id)
        if download is None:
            continue
        download.state = "downloading"
        download.next_retry_at = None
        download.last_error = None
        download.updated_at = now
        session.add(download)


def _select_retriable_downloads(
    session: Session,
    *,
    now: datetime,
    limit: int,
    max_attempts: int,
) -> list[Download]:
    stmt: Select[Download] = (
        select(Download)
        .where(
            Download.state == "failed",
            Download.next_retry_at.is_not(None),
            Download.next_retry_at <= now,
            Download.retry_count <= max_attempts,
        )
        .order_by(Download.next_retry_at.asc())
        .limit(limit)
    )
    return session.execute(stmt).scalars().all()


def _prepare_retry_candidate(record: Download) -> tuple[_RetryCandidate | None, str | None]:
    payload = dict(record.request_payload or {})
    file_info = payload.get("file")
    if not isinstance(file_info, Mapping):
        return None, "missing request payload for retry"

    username = payload.get("username") or record.username
    if not username:
        return None, "missing username for retry"

    file_payload = dict(file_info)
    file_payload["download_id"] = int(record.id)

    priority_source = file_payload.get("priority") or payload.get("priority") or record.priority
    priority = _coerce_priority(priority_source)
    if "priority" not in file_payload:
        file_payload["priority"] = priority

    job_payload: dict[str, Any] = {
        key: value for key, value in payload.items() if key not in {"file", "files"}
    }
    job_payload.update(
        {
            "username": username,
            "files": [file_payload],
            "priority": priority,
        }
    )
    job_payload.setdefault("idempotency_key", f"retry:{record.id}")

    candidate = _RetryCandidate(
        download_id=int(record.id),
        retry_count=int(record.retry_count or 0),
        username=str(username),
        job_payload=job_payload,
        priority=priority,
        idempotency_key=str(job_payload["idempotency_key"]),
    )
    return candidate, None


async def _handle_retry_enqueue_failure(
    candidate: _RetryCandidate,
    error: Exception,
    deps: RetryHandlerDeps,
) -> None:
    message = truncate_error(str(error))
    logger.error(
        "event=retry_enqueue download_id=%s result=error error=%s",
        candidate.download_id,
        error,
    )

    now = deps.now_factory()
    policy = deps.retry_policy
    with deps.session_factory() as session:
        record = session.get(Download, candidate.download_id)
        if record is None:
            return
        record.state = "failed"
        record.last_error = message
        delay = calculate_retry_backoff_seconds(
            int(record.retry_count or candidate.retry_count),
            policy,
            deps.rng,
        )
        record.next_retry_at = now + timedelta(seconds=delay)
        record.updated_at = now
        session.add(record)

    record_activity(
        "download",
        DOWNLOAD_RETRY_FAILED,
        details={
            "downloads": [
                {
                    "download_id": candidate.download_id,
                    "retry_count": candidate.retry_count,
                }
            ],
            "error": message,
            "username": candidate.username,
        },
    )


async def _reschedule_retry_scan(
    *,
    deps: RetryHandlerDeps,
    delay_seconds: float,
    batch_limit: int,
    enabled: bool,
) -> None:
    if not enabled:
        return
    try:
        await _invoke_with_timeout(
            enqueue_retry_scan_job(
                delay_seconds=delay_seconds,
                batch_limit=batch_limit,
                scan_interval=delay_seconds or deps.scan_interval,
                idempotency_key=deps.retry_job_idempotency_key,
                job_type=deps.retry_job_type,
                auto_reschedule=enabled,
                now_factory=deps.now_factory,
            ),
            deps.external_timeout_ms,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("event=retry_reschedule result=error error=%s", exc)


async def handle_retry(
    job: QueueJobDTO,
    deps: RetryHandlerDeps,
) -> Mapping[str, Any]:
    payload = dict(job.payload or {})
    batch_limit = _coerce_positive_int(payload.get("batch_limit"), deps.batch_limit)
    if batch_limit <= 0:
        batch_limit = deps.batch_limit

    scan_interval = _coerce_positive_float(payload.get("scan_interval"), deps.scan_interval)
    reschedule_override = payload.get("reschedule_in")
    if reschedule_override is not None:
        try:
            override_value = float(reschedule_override)
        except (TypeError, ValueError):
            override_value = scan_interval
        else:
            if override_value >= 0:
                scan_interval = override_value

    should_reschedule = _coerce_bool(payload.get("auto_reschedule"), deps.auto_reschedule)

    now = deps.now_factory()
    policy = deps.retry_policy
    candidates: list[_RetryCandidate] = []
    dead_letters: list[Mapping[str, Any]] = []

    with deps.session_factory() as session:
        records = _select_retriable_downloads(
            session,
            now=now,
            limit=batch_limit,
            max_attempts=policy.max_attempts,
        )
        for record in records:
            candidate, error_message = _prepare_retry_candidate(record)
            if candidate is None:
                reason = truncate_error(error_message or "invalid retry payload")
                record.state = "dead_letter"
                record.next_retry_at = None
                record.last_error = reason
                record.updated_at = now
                session.add(record)
                dead_letters.append(
                    {
                        "download_id": int(record.id),
                        "retry_count": int(record.retry_count or 0),
                        "error": reason,
                    }
                )
                logger.warning(
                    "event=retry_dead_letter download_id=%s retry_count=%s result=dead_letter",
                    record.id,
                    record.retry_count,
                )
                continue

            record.state = "queued"
            record.next_retry_at = None
            record.updated_at = now
            session.add(record)
            candidates.append(candidate)
            logger.info(
                "event=retry_claim download_id=%s retry_count=%s result=claimed",
                candidate.download_id,
                candidate.retry_count,
            )

    scheduled: list[Mapping[str, Any]] = []
    failures: list[Mapping[str, Any]] = []

    for candidate in candidates:
        try:
            await _invoke_with_timeout(
                deps.submit_sync_job(
                    candidate.job_payload,
                    priority=candidate.priority,
                    idempotency_key=candidate.idempotency_key,
                ),
                deps.external_timeout_ms,
            )
        except Exception as exc:
            message = truncate_error(str(exc))
            failures.append(
                {
                    "download_id": candidate.download_id,
                    "retry_count": candidate.retry_count,
                    "error": message,
                }
            )
            await _handle_retry_enqueue_failure(candidate, exc, deps)
        else:
            scheduled.append(
                {
                    "download_id": candidate.download_id,
                    "retry_count": candidate.retry_count,
                }
            )

    await _reschedule_retry_scan(
        deps=deps,
        delay_seconds=max(0.0, scan_interval),
        batch_limit=batch_limit,
        enabled=should_reschedule,
    )

    return {
        "claimed": len(candidates),
        "scheduled": scheduled,
        "dead_letter": dead_letters,
        "failed": failures,
        "batch_limit": batch_limit,
        "rescheduled_in": max(0.0, scan_interval) if should_reschedule else None,
    }


def build_retry_handler(
    deps: RetryHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    async def _handler(job: QueueJobDTO) -> Mapping[str, Any]:
        return await handle_retry(job, deps)

    return _handler


async def handle_sync(
    job: QueueJobDTO,
    deps: SyncHandlerDeps,
) -> Mapping[str, Any] | None:
    """Process a sync job via orchestrator dependencies."""

    payload = dict(job.payload or {})
    return await process_sync_payload(payload, deps)


def build_sync_handler(
    deps: SyncHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any] | None]]:
    """Return a dispatcher-compatible handler bound to the given dependencies."""

    async def _handler(job: QueueJobDTO) -> Mapping[str, Any] | None:
        return await handle_sync(job, deps)

    return _handler


async def process_sync_payload(
    payload: Mapping[str, Any], deps: SyncHandlerDeps
) -> Mapping[str, Any] | None:
    username = payload.get("username")
    files = payload.get("files", [])
    if not username or not files:
        logger.warning("Invalid download job received: %s", payload)
        return None

    download_ids: list[int] = []
    with deps.session_factory() as session:
        filtered_files = _filter_active_files(files, session=session)
        if not filtered_files:
            logger.debug("All downloads in job filtered before processing")
            return None
        _mark_downloading(session, filtered_files)
        for file_info in filtered_files:
            identifier = file_info.get("download_id") or file_info.get("id")
            download_id = _extract_download_id(identifier)
            if download_id is not None:
                download_ids.append(download_id)

    try:
        await _invoke_with_timeout(
            deps.soulseek_client.download({"username": username, "files": filtered_files}),
            deps.external_timeout_ms,
        )
    except Exception as exc:
        logger.error("Failed to queue Soulseek download: %s", exc)
        await handle_sync_download_failure(payload, filtered_files, deps, exc)
        raise

    await handle_sync_retry_success(filtered_files, deps)
    return {"username": username, "download_ids": download_ids}


async def handle_sync_download_failure(
    job: Mapping[str, Any],
    files: Iterable[Mapping[str, Any]],
    deps: SyncHandlerDeps,
    error: Exception | str,
) -> None:
    file_list = list(files)
    if not file_list:
        return

    scheduled: list[Mapping[str, Any]] = []
    dead_letters: list[Mapping[str, Any]] = []
    username = job.get("username")
    error_message = truncate_error(str(error))
    now = datetime.utcnow()
    policy = deps.retry_policy
    provider = deps.retry_policy_provider or get_retry_policy_provider()
    deps.retry_policy_provider = provider
    policy_ttl = provider.reload_interval

    with deps.session_factory() as session:
        for file_info in file_list:
            identifier = file_info.get("download_id") or file_info.get("id")
            download_id = _extract_download_id(identifier)
            if download_id is None:
                continue

            download = session.get(Download, download_id)
            if download is None:
                continue

            download.username = username or download.username
            download.retry_count = int(download.retry_count or 0) + 1
            download.last_error = error_message or None
            download.job_id = None
            download.progress = 0.0
            download.updated_at = now

            if download.retry_count > policy.max_attempts:
                download.state = "dead_letter"
                download.next_retry_at = None
                dead_letters.append(
                    {
                        "download_id": download_id,
                        "retry_count": download.retry_count,
                    }
                )
                ingest_item_id = extract_ingest_item_id(download.request_payload)
                if ingest_item_id is not None:
                    update_ingest_item_state(
                        ingest_item_id,
                        IngestItemState.FAILED,
                        error=error_message or None,
                    )
            else:
                delay_seconds = calculate_retry_backoff_seconds(
                    download.retry_count, policy, deps.rng
                )
                download.state = "failed"
                download.next_retry_at = now + timedelta(seconds=delay_seconds)
                meta = {
                    "policy_ttl_s": policy_ttl,
                    "attempt": int(download.retry_count),
                    "max_attempts": int(policy.max_attempts),
                    "backoff_ms": int(delay_seconds * 1000),
                    "jitter_pct": float(policy.jitter_pct),
                }
                if policy.timeout_seconds is not None:
                    meta["timeout_s"] = float(policy.timeout_seconds)
                log_event(
                    logger,
                    "worker.retry",
                    component="orchestrator.sync",
                    entity_id=str(download_id),
                    job_type="sync",
                    status="scheduled",
                    attempts=int(download.retry_count),
                    retry_in=int(delay_seconds),
                    error=error_message or None,
                    meta=meta,
                )
                scheduled.append(
                    {
                        "download_id": download_id,
                        "retry_count": download.retry_count,
                        "delay_seconds": delay_seconds,
                        "next_retry_at": download.next_retry_at.isoformat(),
                    }
                )

            session.add(download)

    if scheduled:
        record_activity(
            "download",
            DOWNLOAD_RETRY_SCHEDULED,
            details={"downloads": scheduled, "username": username},
        )
    if dead_letters:
        record_activity(
            "download",
            DOWNLOAD_RETRY_FAILED,
            details={"downloads": dead_letters, "username": username, "error": error_message},
        )


async def handle_sync_retry_success(
    files: Iterable[Mapping[str, Any]], deps: SyncHandlerDeps
) -> None:
    completed: list[Mapping[str, Any]] = []
    now = datetime.utcnow()

    with deps.session_factory() as session:
        for file_info in files:
            identifier = file_info.get("download_id") or file_info.get("id")
            download_id = _extract_download_id(identifier)
            if download_id is None:
                continue

            download = session.get(Download, download_id)
            if download is None:
                continue

            attempts = int(download.retry_count or 0)
            download.next_retry_at = None
            download.last_error = None
            download.state = "downloading"
            download.updated_at = now
            session.add(download)

            if attempts > 0:
                completed.append({"download_id": download_id, "retry_count": attempts})

    if completed:
        record_activity(
            "download",
            DOWNLOAD_RETRY_COMPLETED,
            details={"downloads": completed},
        )


def extract_ingest_item_id(*payloads: Mapping[str, Any] | None) -> Optional[int]:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        candidate = payload.get("ingest_item_id")
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def update_ingest_item_state(
    item_id: int,
    state: IngestItemState | str,
    *,
    error: Optional[str],
) -> None:
    with session_scope() as session:
        item = session.get(IngestItem, item_id)
        if item is None:
            return
        item.state = state.value if isinstance(state, IngestItemState) else str(state)
        item.error = error
        session.add(item)


def extract_spotify_id(payload: Mapping[str, Any] | None) -> Optional[str]:
    if not isinstance(payload, Mapping):
        return None
    keys = (
        "spotify_id",
        "spotifyId",
        "spotify_track_id",
        "spotifyTrackId",
        "spotify_track",
    )
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = value.get("id")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    nested = payload.get("track")
    if isinstance(nested, Mapping):
        candidate = nested.get("spotify_id") or nested.get("id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def extract_spotify_album_id(
    *payloads: Mapping[str, Any] | None,
) -> Optional[str]:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        direct = payload.get("spotify_album_id") or payload.get("album_id")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        album_payload = payload.get("album")
        if isinstance(album_payload, Mapping):
            for key in ("spotify_id", "spotifyId", "id"):
                value = album_payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        track_payload = payload.get("track")
        if isinstance(track_payload, Mapping):
            album_info = track_payload.get("album")
            if isinstance(album_info, Mapping):
                for key in ("spotify_id", "spotifyId", "id"):
                    value = album_info.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    return None


def resolve_download_path(
    *payloads: Mapping[str, Any] | None,
) -> Optional[str]:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for key in (
            "local_path",
            "localPath",
            "path",
            "file_path",
            "filePath",
            "filename",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _normalise_metadata_value(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, Mapping):
        for key in ("name", "title", "value"):
            nested = _normalise_metadata_value(value.get(key))
            if nested:
                return nested
    if isinstance(value, list) and value:
        return _normalise_metadata_value(value[0])
    return None


def resolve_text(
    keys: Iterable[str],
    *payloads: Mapping[str, Any] | None,
) -> Optional[str]:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for key in keys:
            if key not in payload:
                continue
            candidate = _normalise_metadata_value(payload.get(key))
            if candidate:
                return candidate
            nested = payload.get("metadata")
            if isinstance(nested, Mapping):
                nested_value = resolve_text(keys, nested)
                if nested_value:
                    return nested_value
    return None


def extract_basic_metadata(payload: Mapping[str, Any] | None) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not isinstance(payload, Mapping):
        return metadata
    keys = ("genre", "composer", "producer", "isrc", "copyright", "artwork_url")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            if text:
                metadata[key] = text
    nested = payload.get("metadata")
    if isinstance(nested, Mapping):
        for key, value in extract_basic_metadata(nested).items():
            metadata.setdefault(key, value)
    return metadata


async def fanout_download_completion(
    download_id: int,
    payload: Mapping[str, Any],
    deps: SyncHandlerDeps,
) -> None:
    with session_scope() as session:
        download = session.get(Download, download_id)
        if download is None:
            return
        request_payload = dict(download.request_payload or {})
        filename = download.filename

    ingest_item_id = extract_ingest_item_id(request_payload, payload)

    file_path = resolve_download_path(payload, request_payload) or filename
    metadata: dict[str, Any] = {}
    artwork_url: str | None = None
    if file_path and deps.metadata_service is not None:
        try:
            metadata = await deps.metadata_service.enqueue(
                download_id,
                Path(file_path),
                payload=payload,
                request_payload=request_payload,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Metadata service failed for download %s: %s", download_id, exc)
        else:
            artwork_url = metadata.get("artwork_url") if isinstance(metadata, Mapping) else None

    metadata = dict(metadata or {})
    for source in (request_payload, payload):
        for key, value in extract_basic_metadata(source).items():
            metadata.setdefault(key, value)

    if not artwork_url:
        fallback_artwork = resolve_text(
            ("artwork_url", "cover_url", "image_url", "thumbnail", "thumb"),
            metadata,
            payload,
            request_payload,
        )
        if fallback_artwork:
            artwork_url = fallback_artwork
            metadata.setdefault("artwork_url", artwork_url)

    spotify_track_id = extract_spotify_id(request_payload)
    if not spotify_track_id:
        spotify_track_id = extract_spotify_id(payload)

    spotify_album_id = extract_spotify_album_id(
        metadata,
        payload,
        request_payload,
    )

    organized_path: Path | None = None
    if download_id is not None:
        with session_scope() as session:
            record = session.get(Download, download_id)
            if record is not None:
                record.state = "completed"
                record.retry_count = 0
                record.next_retry_at = None
                record.last_error = None
                record.job_id = None
                if file_path:
                    record.filename = str(file_path)
                    existing_path = (
                        Path(record.organized_path)
                        if isinstance(record.organized_path, str)
                        else None
                    )
                    if existing_path is not None and existing_path.exists():
                        file_path = str(existing_path)
                        record.filename = file_path
                    else:
                        payload_copy: dict[str, Any] = dict(record.request_payload or {})
                        nested_metadata: dict[str, Any] = dict(payload_copy.get("metadata") or {})
                        for key, value in metadata.items():
                            if isinstance(value, (str, int, float)):
                                text = str(value).strip()
                                if text and key not in nested_metadata:
                                    nested_metadata[key] = text
                        if nested_metadata:
                            payload_copy["metadata"] = nested_metadata
                            record.request_payload = payload_copy
                        try:
                            target_dir = (
                                deps.music_dir
                                or Path(os.getenv("MUSIC_DIR", "./music")).expanduser()
                            )
                            organized_path = organize_file(record, target_dir)
                        except FileNotFoundError:
                            logger.debug("Download file missing for organization: %s", file_path)
                        except Exception as exc:  # pragma: no cover - defensive
                            logger.warning("Failed to organise download %s: %s", download_id, exc)
                        else:
                            file_path = str(organized_path)

                if spotify_track_id:
                    record.spotify_track_id = spotify_track_id
                if spotify_album_id:
                    record.spotify_album_id = spotify_album_id
                if artwork_url:
                    record.artwork_url = artwork_url
                if organized_path is not None:
                    record.organized_path = str(organized_path)
                    record.filename = str(organized_path)
                record.updated_at = datetime.utcnow()
                session.add(record)

    if deps.artwork_service is not None and file_path:
        try:
            await deps.artwork_service.enqueue(
                download_id,
                str(file_path),
                metadata=dict(metadata),
                spotify_track_id=spotify_track_id,
                spotify_album_id=spotify_album_id,
                artwork_url=artwork_url,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Failed to schedule artwork embedding for download %s: %s", download_id, exc
            )

    if deps.lyrics_service is not None and file_path:
        track_info: dict[str, Any] = dict(metadata)
        track_info.setdefault("filename", filename)
        track_info.setdefault("download_id", download_id)
        if spotify_track_id:
            track_info.setdefault("spotify_track_id", spotify_track_id)

        title = track_info.get("title") or resolve_text(
            ("title", "track", "name", "filename"),
            metadata,
            payload,
            request_payload,
        )
        track_info["title"] = title or filename

        artist = track_info.get("artist") or resolve_text(
            ("artist", "artist_name", "artists"),
            metadata,
            payload,
            request_payload,
        )
        if artist:
            track_info["artist"] = artist

        album = track_info.get("album") or resolve_text(
            ("album", "album_name", "release"),
            metadata,
            payload,
            request_payload,
        )
        if album:
            track_info["album"] = album

        duration = track_info.get("duration") or resolve_text(
            ("duration", "duration_ms", "durationMs", "length"),
            metadata,
            payload,
            request_payload,
        )
        if duration:
            track_info["duration"] = duration

        try:
            await deps.lyrics_service.enqueue(download_id, str(file_path), track_info)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Failed to schedule lyrics generation for download %s: %s", download_id, exc
            )

    if ingest_item_id is not None:
        update_ingest_item_state(ingest_item_id, IngestItemState.COMPLETED, error=None)


async def enqueue_spotify_backfill(
    service: "SpotifyDomainService",
    *,
    max_items: int | None,
    expand_playlists: bool,
) -> str:
    """Schedule a Spotify backfill job and return its identifier."""

    job = service.create_backfill_job(
        max_items=max_items,
        expand_playlists=expand_playlists,
    )
    await service.enqueue_backfill(job)
    return job.id


def get_spotify_backfill_status(
    service: "SpotifyDomainService", job_id: str
) -> Optional[BackfillJobStatus]:
    """Return the current status for the given Spotify backfill job."""

    return service.get_backfill_status(job_id)


async def enqueue_spotify_free_import(
    service: "SpotifyDomainService",
    *,
    playlist_links: Sequence[str] | None,
    tracks: Sequence[str] | None,
    batch_hint: int | None,
) -> "IngestSubmission":
    """Schedule a Spotify FREE import job via the domain service."""

    return await service._submit_free_import(  # pragma: no cover - exercised via service tests
        playlist_links=playlist_links,
        tracks=tracks,
        batch_hint=batch_hint,
    )


def get_spotify_free_import_job(
    service: "SpotifyDomainService", job_id: str
) -> Optional["JobStatus"]:
    """Fetch the current state for a Spotify FREE import job."""

    return service.get_free_ingest_job(job_id)


__all__ = [
    "SyncRetryPolicy",
    "SyncHandlerDeps",
    "RetryHandlerDeps",
    "MatchingHandlerDeps",
    "ArtistRefreshHandlerDeps",
    "ArtistDeltaHandlerDeps",
    "WatchlistHandlerDeps",
    "MatchingJobError",
    "WatchlistProcessingError",
    "build_sync_handler",
    "build_retry_handler",
    "build_matching_handler",
    "build_artist_refresh_handler",
    "build_artist_delta_handler",
    "build_watchlist_handler",
    "artist_refresh",
    "artist_delta",
    "handle_sync",
    "handle_retry",
    "handle_matching",
    "handle_artist_refresh",
    "handle_artist_delta",
    "handle_watchlist",
    "calculate_retry_backoff_seconds",
    "enqueue_sync_job",
    "enqueue_artist_delta_job",
    "enqueue_retry_scan_job",
    "enqueue_spotify_backfill",
    "fanout_download_completion",
    "get_spotify_backfill_status",
    "enqueue_spotify_free_import",
    "get_spotify_free_import_job",
    "load_sync_retry_policy",
    "load_matching_confidence_threshold",
    "process_sync_payload",
    "truncate_error",
    "extract_ingest_item_id",
    "update_ingest_item_state",
    "extract_spotify_id",
    "extract_spotify_album_id",
    "resolve_download_path",
    "resolve_text",
    "extract_basic_metadata",
]
