"""Soulseek (slskd) adapter implementing asynchronous track search."""

from __future__ import annotations

from math import floor
from time import perf_counter
from typing import Any, Iterable, Mapping

from app.errors import rate_limit_meta
from app.integrations.base import Album, Artist, MusicProvider, Playlist, ProviderError, Track
from app.integrations.slskd_client import (
    SlskdClientError,
    SlskdHTTPStatusError,
    SlskdHttpClient,
    SlskdInvalidResponseError,
    SlskdRateLimitedError,
    SlskdTimeoutError,
)
from app.logging import get_logger
from app.schemas.music import Track as IntegrationTrack


logger = get_logger(__name__)

_MAX_LIMIT = 50


class SlskdAdapterError(RuntimeError):
    """Base exception raised for adapter level failures."""


class SlskdAdapterRateLimitedError(SlskdAdapterError):
    """Raised when slskd rejected the request due to rate limits."""

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None,
        fallback_retry_after_ms: int,
    ) -> None:
        normalized_headers = {str(key).lower(): value for key, value in (headers or {}).items()}
        retry_after_header = normalized_headers.get("retry-after")
        header_payload = {"Retry-After": retry_after_header} if retry_after_header else {}
        meta, _ = rate_limit_meta(header_payload)
        retry_after_ms = meta.get("retry_after_ms") if meta else None
        if retry_after_ms is None:
            retry_after_ms = max(0, fallback_retry_after_ms)
        super().__init__("slskd rate limited the request")
        self.retry_after_ms = retry_after_ms
        self.retry_after_header = retry_after_header
        self.headers = dict(headers or {})


class SlskdAdapterDependencyError(SlskdAdapterError):
    """Raised when upstream dependency errors occur."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SlskdAdapterInternalError(SlskdAdapterError):
    """Raised when the adapter failed to normalise results."""


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    if value is None:
        return []
    return [value]


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
    if isinstance(value, str) and value.strip().lstrip("-+").isdigit():
        try:
            return int(value.strip())
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


def _coerce_duration_seconds(value: Any) -> int | None:
    duration = _coerce_float(value)
    if duration is None:
        return None
    if duration <= 0:
        return None
    if duration > 10_000:  # treat as milliseconds
        duration /= 1000
    return max(0, int(floor(duration)))


def _extract_artists(payload: Any) -> list[str]:
    if isinstance(payload, list):
        artists: list[str] = []
        for entry in payload:
            name = _coerce_str(entry.get("name")) if isinstance(entry, dict) else _coerce_str(entry)
            if name:
                artists.append(name)
        return artists
    name = _coerce_str(payload)
    return [name] if name else []


def _external_id(entry: Mapping[str, Any]) -> str:
    for key in ("id", "token", "objectKey", "path", "magnet", "filename"):
        candidate = entry.get(key)
        text = _coerce_str(candidate)
        if text:
            return text
    username = _coerce_str(entry.get("username"))
    path = _coerce_str(entry.get("path"))
    title = _coerce_str(entry.get("title"))
    components = [component for component in (username, path, title) if component]
    if components:
        return "::".join(components)
    return "slskd-track"


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
    yield payload


def _normalise_track(entry: Mapping[str, Any]) -> IntegrationTrack:
    title = _coerce_str(entry.get("title") or entry.get("name") or entry.get("filename"))
    if not title:
        title = "Unknown Track"
    artists = _extract_artists(entry.get("artists") or entry.get("artist"))
    track: IntegrationTrack = {
        "title": title,
        "artists": artists,
        "source": "slskd",
        "external_id": _external_id(entry),
    }
    album = _coerce_str(entry.get("album"))
    if album:
        track["album"] = album
    duration = _coerce_duration_seconds(
        entry.get("duration_s")
        or entry.get("duration")
        or entry.get("length")
        or entry.get("duration_ms")
    )
    if duration is not None:
        track["duration_s"] = duration
    bitrate = _coerce_int(entry.get("bitrate") or entry.get("bitrate_kbps"))
    if bitrate is not None:
        track["bitrate_kbps"] = max(0, bitrate)
    size = _coerce_int(entry.get("size") or entry.get("size_bytes") or entry.get("filesize"))
    if size is not None:
        track["size_bytes"] = max(0, size)
    path = _coerce_str(entry.get("magnet") or entry.get("magnet_uri") or entry.get("path"))
    if path:
        track["magnet_or_path"] = path
    score = _coerce_float(entry.get("score"))
    if score is not None:
        track["score"] = score
    return track


class SlskdAdapter(MusicProvider):
    """Adapter mapping slskd search results to Harmony's track schema."""

    name = "slskd"

    def __init__(
        self,
        *,
        client: SlskdHttpClient,
        timeout_ms: int,
        rate_limit_fallback_ms: int,
    ) -> None:
        self._client = client
        self._timeout_ms = max(timeout_ms, 100)
        self._rate_limit_fallback_ms = max(0, rate_limit_fallback_ms)

    async def search_tracks(  # type: ignore[override]
        self,
        query: str,
        *,
        limit: int = 20,
        timeout_ms: int | None = None,
    ) -> list[IntegrationTrack]:
        """Perform a slskd search and normalise the results."""

        effective_limit = max(1, min(limit, _MAX_LIMIT))
        resolved_timeout = timeout_ms if timeout_ms is not None else self._timeout_ms
        started = perf_counter()
        try:
            payload = await self._client.search_tracks(
                query,
                limit=effective_limit,
                timeout_ms=resolved_timeout,
            )
        except SlskdRateLimitedError as exc:
            duration_ms = int((perf_counter() - started) * 1000)
            logger.warning(
                "slskd search rate limited",
                extra={
                    "event": "slskd.search",
                    "status": "error",
                    "duration_ms": duration_ms,
                    "limit": effective_limit,
                    "upstream_status": 429,
                },
            )
            raise SlskdAdapterRateLimitedError(
                headers=exc.headers,
                fallback_retry_after_ms=self._rate_limit_fallback_ms,
            ) from exc
        except (SlskdTimeoutError, SlskdHTTPStatusError) as exc:
            duration_ms = int((perf_counter() - started) * 1000)
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "slskd search dependency failure",
                extra={
                    "event": "slskd.search",
                    "status": "error",
                    "duration_ms": duration_ms,
                    "limit": effective_limit,
                    "upstream_status": status_code,
                },
            )
            raise SlskdAdapterDependencyError(
                "slskd search request failed",
                status_code=status_code,
            ) from exc
        except (SlskdInvalidResponseError, SlskdClientError) as exc:
            duration_ms = int((perf_counter() - started) * 1000)
            logger.error(
                "slskd search returned an invalid payload",
                extra={
                    "event": "slskd.search",
                    "status": "error",
                    "duration_ms": duration_ms,
                    "limit": effective_limit,
                },
            )
            raise SlskdAdapterInternalError("Failed to decode slskd search results") from exc

        try:
            tracks: list[IntegrationTrack] = []
            for entry in _iter_files(payload):
                if not isinstance(entry, Mapping):
                    continue
                tracks.append(_normalise_track(entry))
                if len(tracks) >= effective_limit:
                    break
        except Exception as exc:  # pragma: no cover - defensive safeguard
            logger.exception(
                "slskd search normalisation failed",
                extra={"event": "slskd.search", "status": "error"},
            )
            raise SlskdAdapterInternalError("Failed to normalise slskd results") from exc

        duration_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "slskd search completed",
            extra={
                "event": "slskd.search",
                "status": "ok",
                "duration_ms": duration_ms,
                "limit": effective_limit,
                "results_count": len(tracks),
                "upstream_status": 200,
            },
        )
        return tracks

    def get_artist(self, artist_id: str) -> Artist:  # pragma: no cover - legacy API
        raise ProviderError(self.name, "Artist metadata is not available from slskd")

    def get_album(self, album_id: str) -> Album:  # pragma: no cover - legacy API
        raise ProviderError(self.name, "Album metadata is not available from slskd")

    def get_artist_top_tracks(
        self, artist_id: str, limit: int = 10
    ) -> Iterable[Track]:  # pragma: no cover - legacy API
        raise ProviderError(self.name, "Top tracks are not available from slskd")

    def get_playlist(self, playlist_id: str) -> Playlist:  # pragma: no cover - legacy API
        raise ProviderError(self.name, "Playlists are not available from slskd")


__all__ = [
    "SlskdAdapter",
    "SlskdAdapterDependencyError",
    "SlskdAdapterError",
    "SlskdAdapterInternalError",
    "SlskdAdapterRateLimitedError",
]
