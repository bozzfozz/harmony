"""Utilities coordinating orchestrated background work."""

from __future__ import annotations

import asyncio
import inspect
import os
import random
import statistics
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
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
from sqlalchemy.orm import Session

from app.config import (
    RetryPolicyConfig,
    WatchlistWorkerConfig,
    resolve_retry_policy,
)
from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import run_session, session_scope
from app.integrations.normalizers import normalize_slskd_candidate, normalize_spotify_track
from app.logging import get_logger
from app.logging_events import log_event
from app.models import Download, IngestItem, IngestItemState, Match
from app.services.backfill_service import BackfillJobStatus
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


@dataclass(slots=True)
class SyncRetryPolicy:
    """Configuration options for persistent download retries."""

    max_attempts: int
    base_seconds: float
    jitter_pct: float


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
    defaults: RetryPolicyConfig | None = None,
) -> SyncRetryPolicy:
    """Resolve the retry policy from parameters or environment defaults."""

    resolved_defaults = defaults or resolve_retry_policy(env)
    resolved_max = _coerce_positive_int(
        resolved_defaults.max_attempts if max_attempts is None else max_attempts,
        resolved_defaults.max_attempts,
    )
    resolved_base = _coerce_positive_float(
        resolved_defaults.base_seconds if base_seconds is None else base_seconds,
        resolved_defaults.base_seconds,
    )

    resolved_jitter = (
        jitter_pct if jitter_pct is not None else resolved_defaults.jitter_pct
    )
    try:
        resolved_jitter = float(resolved_jitter)
    except (TypeError, ValueError):
        resolved_jitter = resolved_defaults.jitter_pct
    if resolved_jitter < 0:
        resolved_jitter = 0.0

    return SyncRetryPolicy(
        max_attempts=int(resolved_max),
        base_seconds=float(resolved_base),
        jitter_pct=float(resolved_jitter),
    )


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
    retry_policy: SyncRetryPolicy = field(default_factory=load_sync_retry_policy)
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


@dataclass(slots=True)
class RetryHandlerDeps:
    """Dependencies required by the orchestrated retry handler."""

    session_factory: Callable[[], AbstractContextManager[Session]] = session_scope
    submit_sync_job: SyncJobSubmitter = enqueue_sync_job
    retry_policy: SyncRetryPolicy = field(default_factory=load_sync_retry_policy)
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
class WatchlistHandlerDeps:
    """Dependencies required by the watchlist orchestrator handler."""

    spotify_client: SpotifyClient
    soulseek_client: SoulseekClient
    config: WatchlistWorkerConfig
    dao: WatchlistDAO = field(default_factory=WatchlistDAO)
    submit_sync_job: SyncJobSubmitter = enqueue_sync_job
    rng: random.Random = field(default_factory=random.Random)
    now_factory: Callable[[], datetime] = datetime.utcnow
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


def _calculate_watchlist_backoff_ms(attempt: int, deps: WatchlistHandlerDeps) -> int:
    base = deps.backoff_base_ms
    exponent = max(int(attempt) - 1, 0)
    delay = base * (2**exponent)
    if delay <= 0:
        return 0
    if deps.jitter_pct > 0:
        spread = delay * deps.jitter_pct
        delay += deps.rng.uniform(-spread, spread)
    return min(max(int(delay), 0), _WATCHLIST_MAX_BACKOFF_MS)


def _watchlist_cooldown_until(deps: WatchlistHandlerDeps) -> datetime:
    now = deps.now_factory()
    if deps.cooldown_minutes <= 0:
        return now
    return now + timedelta(minutes=deps.cooldown_minutes)


async def _watchlist_dao_call(deps: WatchlistHandlerDeps, method_name: str, /, *args, **kwargs):
    method = getattr(deps.dao, method_name)
    if deps.db_mode == "thread":
        return await asyncio.to_thread(method, *args, **kwargs)
    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _watchlist_build_search_query(
    artist_name: str, album: Mapping[str, Any], track: Mapping[str, Any]
) -> str:
    parts: list[str] = []
    candidate_artist = artist_name or _watchlist_primary_artist(track, album)
    if candidate_artist:
        parts.append(candidate_artist.strip())
    title = track.get("name") or track.get("title")
    if title:
        parts.append(str(title).strip())
    album_name = album.get("name")
    if album_name:
        parts.append(str(album_name).strip())
    return " ".join(part for part in parts if part)


def _watchlist_primary_artist(track: Mapping[str, Any], album: Mapping[str, Any]) -> str:
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


def _watchlist_select_candidate(
    result: Any,
) -> tuple[str | None, Mapping[str, Any] | None]:
    if isinstance(result, Mapping):
        entries = result.get("results")
        if isinstance(entries, list):
            for entry in entries:
                username, file_info = _watchlist_extract_candidate(entry)
                if username and file_info:
                    return username, file_info
    elif isinstance(result, list):
        for entry in result:
            username, file_info = _watchlist_extract_candidate(entry)
            if username and file_info:
                return username, file_info
    return None, None


def _watchlist_extract_candidate(
    candidate: Any,
) -> tuple[str | None, Mapping[str, Any] | None]:
    if not isinstance(candidate, Mapping):
        return None, None
    username = candidate.get("username")
    files = candidate.get("files")
    if isinstance(files, list):
        for file_info in files:
            if isinstance(file_info, Mapping):
                enriched = dict(file_info)
                if "filename" not in enriched and "name" in enriched:
                    enriched["filename"] = enriched["name"]
                return username, enriched
    return None, None


def _watchlist_extract_priority(payload: Mapping[str, Any]) -> int:
    value = payload.get("priority")
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _watchlist_is_new_release(album: Mapping[str, Any], last_checked: datetime | None) -> bool:
    if last_checked is None:
        return True
    release_date = _watchlist_parse_release_date(album)
    if release_date is None:
        return False
    return release_date > last_checked


def _watchlist_parse_release_date(album: Mapping[str, Any]) -> datetime | None:
    value = album.get("release_date")
    if not value:
        return None
    precision = str(album.get("release_date_precision") or "day").lower()
    try:
        if precision == "day":
            return datetime.strptime(str(value), "%Y-%m-%d")
        if precision == "month":
            return datetime.strptime(str(value), "%Y-%m")
        if precision == "year":
            return datetime.strptime(str(value), "%Y")
    except ValueError:
        return None
    return None


async def _watchlist_process_artist(artist: WatchlistArtistRow, deps: WatchlistHandlerDeps) -> int:
    try:
        albums = await _invoke_with_timeout(
            asyncio.to_thread(
                deps.spotify_client.get_artist_albums,
                artist.spotify_artist_id,
            ),
            deps.spotify_timeout_ms,
        )
    except asyncio.TimeoutError as exc:
        raise WatchlistProcessingError(
            "timeout",
            f"spotify albums timeout for {artist.spotify_artist_id}",
            retryable=True,
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
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

    last_checked = artist.last_checked
    recent_albums = [
        album for album in album_list if _watchlist_is_new_release(album, last_checked)
    ]
    if not recent_albums:
        return 0

    track_candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for album in recent_albums:
        album_id = str(album.get("id") or "").strip()
        if not album_id:
            continue
        try:
            tracks = await _invoke_with_timeout(
                asyncio.to_thread(deps.spotify_client.get_album_tracks, album_id),
                deps.spotify_timeout_ms,
            )
        except asyncio.TimeoutError as exc:
            raise WatchlistProcessingError(
                "timeout",
                f"spotify tracks timeout for album {album_id}",
                retryable=True,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
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
            track_id = str(track.get("id") or "").strip()
            if not track_id:
                continue
            track_candidates.append((album, track))

    if not track_candidates:
        return 0

    track_ids = [
        str(track.get("id"))
        for _, track in track_candidates
        if isinstance(track.get("id"), (str, int))
    ]
    existing: set[str] = set()
    if track_ids:
        fetched = await _watchlist_dao_call(deps, "load_existing_track_ids", track_ids)
        if fetched:
            existing = {str(item) for item in fetched}

    queued = 0
    scheduled: set[str] = set()
    for album, track in track_candidates:
        track_id = str(track.get("id") or "").strip()
        if not track_id or track_id in existing or track_id in scheduled:
            continue
        scheduled.add(track_id)
        if await _watchlist_schedule_download(artist, album, track, deps):
            queued += 1
    return queued


async def _watchlist_schedule_download(
    artist: WatchlistArtistRow,
    album: Mapping[str, Any],
    track: Mapping[str, Any],
    deps: WatchlistHandlerDeps,
) -> bool:
    query = _watchlist_build_search_query(artist.name, album, track)
    if not query:
        return False
    try:
        results = await _invoke_with_timeout(
            deps.soulseek_client.search(query),
            deps.search_timeout_ms,
        )
    except asyncio.TimeoutError as exc:
        raise WatchlistProcessingError(
            "timeout", f"search timeout for {query}", retryable=True
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        raise WatchlistProcessingError(
            "dependency_error",
            f"search failed for {query}: {exc}",
            retryable=True,
        ) from exc

    username, file_info = _watchlist_select_candidate(results)
    if not username or not file_info:
        log_event(
            logger,
            "watchlist.search",
            component=_WATCHLIST_LOG_COMPONENT,
            status="empty",
            entity_id=artist.spotify_artist_id,
            query=query,
        )
        return False

    payload = dict(file_info)
    filename = str(payload.get("filename") or payload.get("name") or track.get("name") or "unknown")
    priority = _watchlist_extract_priority(payload)
    track_id = str(track.get("id") or "").strip()
    album_id = str(album.get("id") or "").strip()

    download_id = await _watchlist_dao_call(
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
        raise WatchlistProcessingError(
            "internal_error",
            f"failed to persist download for {filename}",
            retryable=False,
        )

    payload = dict(payload)
    payload["download_id"] = int(download_id)
    payload.setdefault("filename", filename)
    payload["priority"] = priority

    job_payload = {
        "username": username,
        "files": [payload],
        "priority": priority,
        "source": "watchlist",
        "idempotency_key": f"watchlist-download:{download_id}",
    }

    try:
        await deps.submit_sync_job(job_payload, priority=priority)
    except Exception as exc:  # pragma: no cover - defensive logging
        await _watchlist_dao_call(deps, "mark_download_failed", int(download_id), str(exc))
        raise WatchlistProcessingError(
            "dependency_error",
            f"failed to enqueue download {download_id}: {exc}",
            retryable=True,
        ) from exc

    log_event(
        logger,
        "watchlist.download",
        component=_WATCHLIST_LOG_COMPONENT,
        status="queued",
        entity_id=artist.spotify_artist_id,
        track_id=track_id,
        download_id=int(download_id),
    )
    return True


async def handle_watchlist(job: QueueJobDTO, deps: WatchlistHandlerDeps) -> Mapping[str, Any]:
    payload = dict(job.payload or {})
    artist_id_raw = payload.get("artist_id")
    if artist_id_raw is None:
        raise MatchingJobError("invalid_payload", "missing artist_id", retry=False)
    try:
        artist_pk = int(artist_id_raw)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive logging
        raise MatchingJobError("invalid_payload", "invalid artist_id", retry=False) from exc

    artist = await _watchlist_dao_call(deps, "get_artist", artist_pk)
    if artist is None:
        log_event(
            logger,
            "watchlist.job",
            component=_WATCHLIST_LOG_COMPONENT,
            status="missing",
            artist_id=artist_pk,
        )
        return {
            "status": "missing",
            "artist_id": artist_pk,
            "queued": 0,
            "attempts": int(job.attempts),
        }

    now = deps.now_factory()
    if artist.retry_block_until and artist.retry_block_until > now:
        log_event(
            logger,
            "watchlist.job",
            component=_WATCHLIST_LOG_COMPONENT,
            status="cooldown",
            entity_id=artist.spotify_artist_id,
            retry_block_until=artist.retry_block_until.isoformat(),
        )
        return {
            "status": "cooldown",
            "artist_id": artist.spotify_artist_id,
            "queued": 0,
            "attempts": int(job.attempts),
            "retry_block_until": artist.retry_block_until.isoformat(),
        }

    cutoff = _parse_iso_datetime(payload.get("cutoff"))
    if cutoff and artist.last_checked and artist.last_checked > cutoff:
        log_event(
            logger,
            "watchlist.job",
            component=_WATCHLIST_LOG_COMPONENT,
            status="noop",
            entity_id=artist.spotify_artist_id,
            reason="stale",
        )
        return {
            "status": "noop",
            "artist_id": artist.spotify_artist_id,
            "queued": 0,
            "attempts": int(job.attempts),
            "reason": "stale",
        }

    attempts = max(int(job.attempts or 0), 1)
    start = time.perf_counter()
    try:
        queued = await _watchlist_process_artist(artist, deps)
    except WatchlistProcessingError as exc:
        if not exc.retryable:
            await _watchlist_dao_call(
                deps,
                "mark_failed",
                artist.id,
                reason=exc.code,
                retry_at=now,
            )
            log_event(
                logger,
                "watchlist.job",
                component=_WATCHLIST_LOG_COMPONENT,
                status="failed",
                entity_id=artist.spotify_artist_id,
                attempts=attempts,
                error=exc.code,
            )
            raise MatchingJobError(exc.code, str(exc), retry=False) from exc

        if attempts >= deps.retry_budget:
            cooldown_until = _watchlist_cooldown_until(deps)
            await _watchlist_dao_call(
                deps,
                "mark_failed",
                artist.id,
                reason="cooldown",
                retry_at=cooldown_until,
                retry_block_until=cooldown_until,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_event(
                logger,
                "watchlist.job",
                component=_WATCHLIST_LOG_COMPONENT,
                status="cooldown",
                entity_id=artist.spotify_artist_id,
                attempts=attempts,
                duration_ms=duration_ms,
                retry_block_until=cooldown_until.isoformat(),
            )
            return {
                "status": "cooldown",
                "artist_id": artist.spotify_artist_id,
                "queued": 0,
                "attempts": attempts,
                "retry_block_until": cooldown_until.isoformat(),
                "duration_ms": duration_ms,
            }

        backoff_ms = _calculate_watchlist_backoff_ms(attempts, deps)
        retry_seconds = max(1, int(backoff_ms / 1000))
        retry_at = deps.now_factory() + timedelta(milliseconds=backoff_ms)
        await _watchlist_dao_call(
            deps,
            "mark_failed",
            artist.id,
            reason=exc.code,
            retry_at=retry_at,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_event(
            logger,
            "watchlist.job",
            component=_WATCHLIST_LOG_COMPONENT,
            status="retry",
            entity_id=artist.spotify_artist_id,
            attempts=attempts,
            duration_ms=duration_ms,
            retry_in=retry_seconds,
            error=exc.code,
        )
        raise MatchingJobError(exc.code, str(exc), retry=True, retry_in=retry_seconds) from exc

    await _watchlist_dao_call(
        deps,
        "mark_success",
        artist.id,
        checked_at=deps.now_factory(),
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    status = "ok" if queued else "noop"
    log_event(
        logger,
        "watchlist.job",
        component=_WATCHLIST_LOG_COMPONENT,
        status=status,
        entity_id=artist.spotify_artist_id,
        queued=queued,
        attempts=attempts,
        duration_ms=duration_ms,
    )
    result: dict[str, Any] = {
        "status": status,
        "artist_id": artist.spotify_artist_id,
        "queued": queued,
        "attempts": attempts,
        "duration_ms": duration_ms,
    }
    return result


def build_watchlist_handler(
    deps: WatchlistHandlerDeps,
) -> Callable[[QueueJobDTO], Awaitable[Mapping[str, Any]]]:
    async def _handler(job: QueueJobDTO) -> Mapping[str, Any]:
        return await handle_watchlist(job, deps)

    return _handler


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
    with deps.session_factory() as session:
        record = session.get(Download, candidate.download_id)
        if record is None:
            return
        record.state = "failed"
        record.last_error = message
        delay = calculate_retry_backoff_seconds(
            int(record.retry_count or candidate.retry_count),
            deps.retry_policy,
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
    candidates: list[_RetryCandidate] = []
    dead_letters: list[Mapping[str, Any]] = []

    with deps.session_factory() as session:
        records = _select_retriable_downloads(
            session,
            now=now,
            limit=batch_limit,
            max_attempts=deps.retry_policy.max_attempts,
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

            if download.retry_count > deps.retry_policy.max_attempts:
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
                    download.retry_count, deps.retry_policy, deps.rng
                )
                download.state = "failed"
                download.next_retry_at = now + timedelta(seconds=delay_seconds)
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
    "WatchlistHandlerDeps",
    "MatchingJobError",
    "build_matching_handler",
    "handle_matching",
    "build_watchlist_handler",
    "handle_watchlist",
    "build_retry_handler",
    "handle_retry",
    "build_sync_handler",
    "calculate_retry_backoff_seconds",
    "enqueue_sync_job",
    "enqueue_retry_scan_job",
    "enqueue_spotify_backfill",
    "fanout_download_completion",
    "get_spotify_backfill_status",
    "enqueue_spotify_free_import",
    "get_spotify_free_import_job",
    "handle_sync",
    "handle_sync_download_failure",
    "handle_sync_retry_success",
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
