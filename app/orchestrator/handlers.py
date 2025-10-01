"""Utilities coordinating orchestrated background work."""

from __future__ import annotations

import asyncio
import os
import random
import statistics
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

from sqlalchemy.orm import Session

from app.core.matching_engine import MusicMatchingEngine
from app.core.soulseek_client import SoulseekClient
from app.db import session_scope
from app.integrations.normalizers import normalize_slskd_candidate, normalize_spotify_track
from app.logging import get_logger
from app.models import Download, IngestItem, IngestItemState, Match
from app.services.backfill_service import BackfillJobStatus
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
from app.workers.persistence import QueueJobDTO


logger = get_logger(__name__)

_DEFAULT_TIMEOUT_MS = 10_000


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


def load_sync_retry_policy(
    *,
    max_attempts: int | None = None,
    base_seconds: float | None = None,
    jitter_pct: float | None = None,
) -> SyncRetryPolicy:
    """Resolve the retry policy from parameters or environment defaults."""

    resolved_max = max_attempts
    if resolved_max is None:
        resolved_max = _safe_int(os.getenv("RETRY_MAX_ATTEMPTS"), 10)
    if resolved_max <= 0:
        resolved_max = 10

    resolved_base = base_seconds
    if resolved_base is None:
        resolved_base = _safe_float(os.getenv("RETRY_BASE_SECONDS"), 60.0)
    if resolved_base <= 0:
        resolved_base = 60.0

    resolved_jitter = jitter_pct
    if resolved_jitter is None:
        resolved_jitter = _safe_float(os.getenv("RETRY_JITTER_PCT"), 0.2)
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


class MetadataService(Protocol):
    async def enqueue(
        self,
        download_id: int,
        file_path: Path,
        *,
        payload: Mapping[str, Any] | None,
        request_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        ...


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
    ) -> Any:
        ...


class LyricsService(Protocol):
    async def enqueue(
        self,
        download_id: int,
        file_path: str,
        track_info: Mapping[str, Any],
    ) -> Any:
        ...


@dataclass(slots=True)
class MatchingHandlerDeps:
    """Dependencies required by the matching orchestrator handler."""

    engine: MusicMatchingEngine
    session_factory: Callable[[], AbstractContextManager[Session]] = session_scope
    confidence_threshold: float = field(default_factory=lambda: load_matching_confidence_threshold())
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
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not candidates:
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

    stored = 0
    spotify_track_id = str(spotify_track.get("id") or "")
    with deps.session_factory() as session:
        for candidate, score in qualifying:
            match = Match(
                source=job_type,
                spotify_track_id=spotify_track_id or None,
                target_id=str(candidate.get("id")) if candidate.get("id") else None,
                confidence=float(score),
            )
            session.add(match)
            stored += 1

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
            {"candidate": candidate, "score": round(score, 4)}
            for candidate, score in qualifying
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
            deps.soulseek_client.download(
                {"username": username, "files": filtered_files}
            ),
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
                        nested_metadata: dict[str, Any] = dict(
                            payload_copy.get("metadata") or {}
                        )
                        for key, value in metadata.items():
                            if isinstance(value, (str, int, float)):
                                text = str(value).strip()
                                if text and key not in nested_metadata:
                                    nested_metadata[key] = text
                        if nested_metadata:
                            payload_copy["metadata"] = nested_metadata
                            record.request_payload = payload_copy
                        try:
                            target_dir = deps.music_dir or Path(os.getenv("MUSIC_DIR", "./music")).expanduser()
                            organized_path = organize_file(record, target_dir)
                        except FileNotFoundError:
                            logger.debug(
                                "Download file missing for organization: %s", file_path
                            )
                        except Exception as exc:  # pragma: no cover - defensive
                            logger.warning(
                                "Failed to organise download %s: %s", download_id, exc
                            )
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
    "MatchingHandlerDeps",
    "MatchingJobError",
    "build_matching_handler",
    "handle_matching",
    "build_sync_handler",
    "calculate_retry_backoff_seconds",
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
