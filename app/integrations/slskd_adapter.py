"""Soulseek (slskd) adapter implementing asynchronous track search."""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
import unicodedata
from dataclasses import dataclass
from time import perf_counter
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

import httpx

from app.errors import rate_limit_meta
from app.integrations.base import MusicProviderAdapter, TrackCandidate
from app.logging import get_logger
from app.utils.text_normalization import clean_track_title, normalize_quotes


logger = get_logger(__name__)

_DEFAULT_SEARCH_PATH = "/api/v0/search/tracks"
_JITTER_PCT = 0.2
_ALLOWED_SCHEMES = {"http", "https"}
_EMPTY_METADATA = MappingProxyType({})


class SlskdAdapterError(RuntimeError):
    """Base exception raised for adapter level failures."""


class SlskdAdapterValidationError(SlskdAdapterError):
    """Raised when the upstream service rejected the request as invalid."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SlskdAdapterRateLimitedError(SlskdAdapterError):
    """Raised when slskd rejected the request due to rate limits."""

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None,
        fallback_retry_after_ms: int,
    ) -> None:
        normalized_headers = {str(key): str(value) for key, value in (headers or {}).items()}
        meta, safe_headers = rate_limit_meta(normalized_headers)
        retry_after_ms = meta.get("retry_after_ms") if meta else None
        if retry_after_ms is None:
            retry_after_ms = max(0, fallback_retry_after_ms)
        retry_after_header = safe_headers.get("Retry-After")
        super().__init__("slskd rate limited the request")
        self.retry_after_ms = retry_after_ms
        self.retry_after_header = retry_after_header
        self.headers = normalized_headers


class SlskdAdapterDependencyError(SlskdAdapterError):
    """Raised when upstream dependency errors occur."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SlskdAdapterInternalError(SlskdAdapterError):
    """Raised when the adapter failed to normalise results."""


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lstrip("-+").isdigit():
            try:
                return int(cleaned)
            except ValueError:  # pragma: no cover - defensive guard
                return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _iter_files(payload: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, list):
        for entry in payload:
            yield from _iter_files(entry)
        return
    if not isinstance(payload, Mapping):
        return
    for key in ("results", "matches", "tracks"):
        if key in payload:
            yield from _iter_files(payload[key])
            return
    files = payload.get("files")
    username = _coerce_str(payload.get("username") or payload.get("user"))
    if files is not None:
        for item in _ensure_list(files):
            if isinstance(item, Mapping):
                if username and "username" not in item:
                    enriched = dict(item)
                    enriched["username"] = username
                    yield enriched
                else:
                    yield item
        return
    if isinstance(payload, Mapping):
        yield payload


def _compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalise_search_value(value: str) -> str:
    cleaned = clean_track_title(value)
    cleaned = normalize_quotes(cleaned)
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = re.sub(
        r"\s*(?:feat\.?|featuring|ft\.?|with)\s+.+$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = cleaned.strip(" -")
    return _compact_whitespace(cleaned)


def _combine_terms(query: str, artist: str | None) -> str:
    parts = [part for part in (artist, query) if part]
    if not parts:
        return ""
    return _compact_whitespace(" - ".join(parts))


def _format_rankings(preferred_formats: Sequence[str]) -> Mapping[str, int]:
    ranking: dict[str, int] = {}
    for index, entry in enumerate(preferred_formats):
        if not entry:
            continue
        normalized = entry.strip().upper()
        if normalized and normalized not in ranking:
            ranking[normalized] = index
    return ranking


def _extract_format(entry: Mapping[str, Any]) -> str | None:
    format_fields = ("format", "file_type", "extension", "ext")
    for key in format_fields:
        candidate = _coerce_str(entry.get(key))
        if candidate:
            return candidate.upper()
    filename = _coerce_str(entry.get("filename") or entry.get("path"))
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1]
        if ext:
            return ext.upper()
    return None


def _extract_artist(entry: Mapping[str, Any]) -> str | None:
    artists = entry.get("artists")
    if isinstance(artists, list):
        for item in artists:
            name = _coerce_str(item.get("name")) if isinstance(item, Mapping) else _coerce_str(item)
            if name:
                return normalize_quotes(name)
    artist = _coerce_str(entry.get("artist") or entry.get("uploader"))
    if artist:
        return normalize_quotes(artist)
    return None


def _extract_title(entry: Mapping[str, Any]) -> str:
    for key in ("title", "name", "filename"):
        candidate = _coerce_str(entry.get(key))
        if candidate:
            return normalize_quotes(candidate)
    return "Unknown Track"


def _extract_seeders(entry: Mapping[str, Any]) -> int | None:
    for key in ("seeders", "user_count", "users", "availability", "count"):
        seeders = _coerce_int(entry.get(key))
        if seeders is not None:
            return max(0, seeders)
    return None


def _extract_availability(entry: Mapping[str, Any], seeders: int | None) -> float | None:
    for key in ("availability", "availability_score", "estimated_availability"):
        availability = _coerce_float(entry.get(key))
        if availability is not None:
            return max(0.0, min(1.0, availability))
    if seeders is not None:
        return max(0.0, min(1.0, seeders / 5.0))
    return None


def _extract_metadata(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {}
    filename = _coerce_str(entry.get("filename"))
    if filename:
        metadata["filename"] = filename
    score = _coerce_float(entry.get("score"))
    if score is not None:
        metadata["score"] = score
    bitrate_mode = _coerce_str(entry.get("bitrate_mode") or entry.get("encoding"))
    if bitrate_mode:
        metadata["bitrate_mode"] = bitrate_mode
    if not metadata:
        return _EMPTY_METADATA
    return MappingProxyType(metadata)


def _build_candidate(entry: Mapping[str, Any]) -> TrackCandidate:
    title = clean_track_title(_extract_title(entry)) or "Unknown Track"
    artist = _extract_artist(entry)
    format_name = _extract_format(entry)
    bitrate = _coerce_int(entry.get("bitrate") or entry.get("bitrate_kbps"))
    if bitrate is not None and bitrate <= 0:
        bitrate = None
    size = _coerce_int(entry.get("size") or entry.get("size_bytes") or entry.get("filesize"))
    if size is not None and size < 0:
        size = None
    seeders = _extract_seeders(entry)
    username = _coerce_str(entry.get("username") or entry.get("user"))
    availability = _extract_availability(entry, seeders)
    download_uri = _coerce_str(entry.get("magnet") or entry.get("magnet_uri") or entry.get("path"))
    metadata = _extract_metadata(entry)
    return TrackCandidate(
        title=title,
        artist=artist,
        format=format_name,
        bitrate_kbps=bitrate,
        size_bytes=size,
        seeders=seeders,
        username=username,
        availability=availability,
        source="slskd",
        download_uri=download_uri,
        metadata=metadata,
    )


def _sort_candidates(
    candidates: list[TrackCandidate], preferred_formats: Mapping[str, int]
) -> list[TrackCandidate]:
    def sort_key(candidate: TrackCandidate) -> tuple[int, int, int, str]:
        format_rank = preferred_formats.get(
            (candidate.format or "").upper(), len(preferred_formats)
        )
        seeders = -(candidate.seeders or 0)
        size = candidate.size_bytes if candidate.size_bytes is not None else 1_000_000_000
        title = candidate.title.lower()
        return (format_rank, seeders, size, title)

    return sorted(candidates, key=sort_key)


@dataclass(slots=True)
class SlskdAdapter(MusicProviderAdapter):
    """Adapter mapping slskd search results to Harmony's track candidate schema."""

    base_url: str
    api_key: str | None
    timeout_ms: int
    max_retries: int
    backoff_base_ms: int
    preferred_formats: tuple[str, ...]
    max_results: int
    client: httpx.AsyncClient | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError("SLSKD_BASE_URL must use http or https")
        normalized_base = parsed.geturl().rstrip("/") or f"{parsed.scheme}://{parsed.netloc}"
        object.__setattr__(self, "_base_url", normalized_base)
        timeout_ms = max(200, int(self.timeout_ms))
        object.__setattr__(self, "_timeout_ms", timeout_ms)
        retries = max(0, int(self.max_retries))
        object.__setattr__(self, "_max_retries", retries)
        backoff = max(50, int(self.backoff_base_ms))
        object.__setattr__(self, "_backoff_base_ms", backoff)
        normalized_formats: list[str] = []
        seen_formats: set[str] = set()
        for entry in self.preferred_formats:
            cleaned = entry.strip().upper()
            if cleaned and cleaned not in seen_formats:
                seen_formats.add(cleaned)
                normalized_formats.append(cleaned)
        formats = tuple(normalized_formats)
        object.__setattr__(self, "_preferred_formats", formats)
        object.__setattr__(self, "_format_ranking", _format_rankings(formats))
        max_results = max(1, int(self.max_results))
        object.__setattr__(self, "_max_results", max_results)
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        object.__setattr__(self, "_headers", headers)
        if self.client is not None:
            object.__setattr__(self, "_client", self.client)
            object.__setattr__(self, "_owns_client", False)
        else:
            timeout = self._build_timeout(timeout_ms)
            client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=timeout,
            )
            object.__setattr__(self, "_client", client)
            object.__setattr__(self, "_owns_client", True)

    name = "slskd"

    async def aclose(self) -> None:
        """Close the underlying HTTP client when owned by the adapter."""

        if getattr(self, "_owns_client", False):
            await self._client.aclose()

    async def search_tracks(
        self,
        query: str,
        *,
        artist: str | None = None,
        limit: int = 50,
    ) -> list[TrackCandidate]:
        trimmed_query = query.strip()
        if not trimmed_query:
            raise SlskdAdapterValidationError("query must not be empty")
        normalized_query = _normalise_search_value(trimmed_query)
        normalized_artist = _normalise_search_value(artist) if artist else None
        combined = _combine_terms(normalized_query, normalized_artist)
        if not combined:
            raise SlskdAdapterValidationError("query must not be empty after normalization")
        effective_limit = max(1, min(int(limit), self._max_results))
        preferred_formats = self._format_ranking
        params = {"query": combined, "limit": effective_limit, "type": "track"}
        q_hash = hashlib.sha1(combined.encode("utf-8")).hexdigest()[:12]
        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            started = perf_counter()
            status_code: int | None = None
            try:
                response = await self._client.get(
                    _DEFAULT_SEARCH_PATH,
                    params=params,
                    headers=self._headers,
                )
                status_code = response.status_code
            except httpx.TimeoutException:
                duration_ms = int((perf_counter() - started) * 1000)
                logger.warning(
                    "slskd search timeout",
                    extra={
                        "event": "slskd.search",
                        "status": "timeout",
                        "attempt": attempt,
                        "q_hash": q_hash,
                        "duration_ms": duration_ms,
                        "limit": effective_limit,
                    },
                )
                error: SlskdAdapterError = SlskdAdapterDependencyError(
                    "slskd search request timed out",
                )
            except httpx.HTTPError:
                duration_ms = int((perf_counter() - started) * 1000)
                logger.warning(
                    "slskd search network failure",
                    extra={
                        "event": "slskd.search",
                        "status": "network-error",
                        "attempt": attempt,
                        "q_hash": q_hash,
                        "duration_ms": duration_ms,
                        "limit": effective_limit,
                    },
                )
                error = SlskdAdapterDependencyError("slskd search request failed")
            else:
                if status_code == httpx.codes.OK:
                    try:
                        payload = response.json()
                    except ValueError as exc:  # pragma: no cover - defensive guard
                        raise SlskdAdapterInternalError("slskd returned invalid JSON") from exc
                    try:
                        candidates = [_build_candidate(entry) for entry in _iter_files(payload)]
                    except Exception as exc:  # pragma: no cover - defensive safeguard
                        logger.exception(
                            "slskd search normalisation failed",
                            extra={"event": "slskd.search", "status": "error", "q_hash": q_hash},
                        )
                        raise SlskdAdapterInternalError(
                            "Failed to normalise slskd results"
                        ) from exc
                    filtered = [
                        candidate
                        for candidate in candidates
                        if isinstance(candidate, TrackCandidate)
                    ]
                    sorted_candidates = _sort_candidates(filtered, preferred_formats)
                    limited = sorted_candidates[:effective_limit]
                    duration_ms = int((perf_counter() - started) * 1000)
                    logger.info(
                        "slskd search completed",
                        extra={
                            "event": "slskd.search",
                            "status": "ok",
                            "attempt": attempt,
                            "q_hash": q_hash,
                            "duration_ms": duration_ms,
                            "limit": effective_limit,
                            "results_count": len(limited),
                            "upstream_status": status_code,
                        },
                    )
                    return limited
                if status_code == httpx.codes.TOO_MANY_REQUESTS:
                    backoff_ms = self._compute_backoff_ms(attempt)
                    error = SlskdAdapterRateLimitedError(
                        headers=response.headers,
                        fallback_retry_after_ms=backoff_ms,
                    )
                elif status_code is not None and 500 <= status_code < 600:
                    error = SlskdAdapterDependencyError(
                        "slskd returned a server error",
                        status_code=status_code,
                    )
                elif status_code is not None and 400 <= status_code < 500:
                    raise SlskdAdapterValidationError(
                        "slskd rejected the search request",
                        status_code=status_code,
                    )
                else:
                    error = SlskdAdapterDependencyError(
                        "slskd responded with an unexpected status",
                        status_code=status_code,
                    )

            should_retry = attempt < attempts and isinstance(
                error, (SlskdAdapterDependencyError, SlskdAdapterRateLimitedError)
            )
            duration_ms = int((perf_counter() - started) * 1000)
            logger.warning(
                "slskd search failed",
                extra={
                    "event": "slskd.search",
                    "status": "error",
                    "attempt": attempt,
                    "q_hash": q_hash,
                    "duration_ms": duration_ms,
                    "limit": effective_limit,
                    "upstream_status": getattr(error, "status_code", status_code),
                },
            )
            if not should_retry:
                raise error
            backoff_ms = self._compute_backoff_ms(attempt)
            await asyncio.sleep(backoff_ms / 1000)
        raise SlskdAdapterDependencyError("slskd search failed after retries")

    def _compute_backoff_ms(self, attempt: int) -> int:
        base = self._backoff_base_ms * (2 ** max(0, attempt - 1))
        jitter_range = base * _JITTER_PCT
        delay = base + random.uniform(-jitter_range, jitter_range)
        return max(0, int(delay))

    @staticmethod
    def _build_timeout(timeout_ms: int) -> httpx.Timeout:
        total_seconds = timeout_ms / 1000
        connect_timeout = min(total_seconds, 5.0)
        return httpx.Timeout(
            total_seconds, connect=connect_timeout, read=total_seconds, write=total_seconds
        )


__all__ = [
    "SlskdAdapter",
    "SlskdAdapterDependencyError",
    "SlskdAdapterError",
    "SlskdAdapterInternalError",
    "SlskdAdapterRateLimitedError",
    "SlskdAdapterValidationError",
]
