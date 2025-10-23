"""Soulseek (slskd) track provider implementation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any
import unicodedata
from urllib.parse import urlparse

import httpx

from app.integrations.base import TrackCandidate
from app.integrations.contracts import (
    ProviderAlbumDetails,
    ProviderArtist,
    ProviderDependencyError,
    ProviderInternalError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderRelease,
    ProviderTimeoutError,
    ProviderTrack,
    ProviderValidationError,
    SearchQuery,
    TrackProvider,
)
from app.integrations.normalizers import (
    from_slskd_album_details,
    from_slskd_artist,
    from_slskd_release,
    normalize_slskd_track,
)
from app.logging import get_logger
from app.utils.text_normalization import clean_track_title, normalize_quotes

logger = get_logger(__name__)

_DEFAULT_SEARCH_PATH = "/api/v0/search/tracks"
_DEFAULT_HEALTH_PATH = "/health"
_ALLOWED_SCHEMES = {"http", "https"}


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
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lstrip("-+").isdigit():
            try:
                return int(cleaned)
            except ValueError:
                return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
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


def _normalize_base_url(value: str) -> str:
    trimmed = (value or "").strip()
    if not trimmed:
        raise RuntimeError("SLSKD_BASE_URL must be configured and non-empty")
    parsed = urlparse(trimmed)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise RuntimeError("SLSKD_BASE_URL must use http or https")
    if not parsed.netloc:
        raise RuntimeError("SLSKD_BASE_URL must include a hostname")
    path = re.sub(r"/{2,}", "/", parsed.path or "")
    path = path.rstrip("/")
    base = f"{scheme}://{parsed.netloc}"
    if path:
        if not path.startswith("/"):
            path = "/" + path
        base = f"{base}{path}"
    return base


def _normalize_path(path: str) -> str:
    cleaned = re.sub(r"/{2,}", "/", (path or "").strip())
    if not cleaned:
        return "/"
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned


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
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _combine_terms(query: str, artist: str | None) -> str:
    if artist:
        return f"{artist} {query}".strip()
    return query


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
    identifier = entry.get("id") or entry.get("track_id")
    if identifier:
        metadata["id"] = identifier
    score = _coerce_float(entry.get("score"))
    if score is not None:
        metadata["score"] = score
    bitrate_mode = _coerce_str(entry.get("bitrate_mode") or entry.get("encoding"))
    if bitrate_mode:
        metadata["bitrate_mode"] = bitrate_mode
    year = _coerce_int(entry.get("year"))
    if year is not None:
        metadata["year"] = year
    genres_field = entry.get("genres")
    if isinstance(genres_field, list | tuple):
        metadata["genres"] = [str(item) for item in genres_field if item]
    genre = _coerce_str(entry.get("genre"))
    if genre:
        metadata["genre"] = genre
    album = _coerce_str(entry.get("album"))
    if album:
        metadata["album"] = album
    artists = entry.get("artists")
    if isinstance(artists, list):
        names: list[str] = []
        for item in artists:
            if isinstance(item, Mapping):
                name = _coerce_str(item.get("name"))
            else:
                name = _coerce_str(item)
            if name:
                names.append(name)
        if names:
            metadata["artists"] = names
    artist = _coerce_str(entry.get("artist"))
    if artist:
        metadata.setdefault("artists", []).append(artist)
    if not metadata:
        return MappingProxyType({})
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
    download_uri = _coerce_str(
        entry.get("download_uri")
        or entry.get("magnet")
        or entry.get("magnet_uri")
        or entry.get("path")
        or entry.get("filename")
    )
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
    def sort_key(candidate: TrackCandidate) -> tuple[int, int, int, int, str]:
        format_rank = preferred_formats.get(
            (candidate.format or "").upper(), len(preferred_formats)
        )
        seeders = -(candidate.seeders or 0)
        bitrate = -candidate.bitrate_kbps if candidate.bitrate_kbps is not None else 0
        size = candidate.size_bytes if candidate.size_bytes is not None else 1_000_000_000
        title = candidate.title.lower()
        return (format_rank, seeders, bitrate, size, title)

    return sorted(candidates, key=sort_key)


def _parse_retry_after_ms(headers: Mapping[str, str]) -> int | None:
    retry_after = headers.get("Retry-After")
    if not retry_after:
        return None
    numeric = _coerce_int(retry_after)
    if numeric is not None:
        return max(0, numeric * 1000)
    return None


@dataclass(slots=True)
class SlskdAdapter(TrackProvider):
    """Adapter mapping slskd search results to Harmony's track provider contract."""

    base_url: str
    api_key: str | None
    timeout_ms: int
    preferred_formats: Sequence[str]
    max_results: int
    client: httpx.AsyncClient | None = None
    search_path: str = _DEFAULT_SEARCH_PATH
    health_path: str = _DEFAULT_HEALTH_PATH
    _base_url: str = field(init=False, repr=False)
    _timeout_ms: int = field(init=False, repr=False)
    _preferred_formats: tuple[str, ...] = field(init=False, repr=False)
    _format_ranking: Mapping[str, int] = field(init=False, repr=False)
    _max_results: int = field(init=False, repr=False)
    _headers: Mapping[str, str] = field(init=False, repr=False)
    _client: httpx.AsyncClient = field(init=False, repr=False)
    _owns_client: bool = field(init=False, repr=False)
    _search_path: str = field(init=False, repr=False)
    _health_path: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        normalized_base = _normalize_base_url(self.base_url)
        object.__setattr__(self, "_base_url", normalized_base)

        api_key = (self.api_key or "").strip()
        if not api_key:
            raise RuntimeError("SLSKD_API_KEY must be configured and non-empty")
        object.__setattr__(self, "api_key", api_key)

        timeout_ms = max(200, int(self.timeout_ms))
        object.__setattr__(self, "_timeout_ms", timeout_ms)

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

        headers = {"Accept": "application/json", "X-API-Key": api_key}
        object.__setattr__(self, "_headers", headers)

        timeout = httpx.Timeout(timeout_ms / 1000, connect=min(timeout_ms / 1000, 5.0))
        client = self.client or httpx.AsyncClient(
            base_url=normalized_base,
            headers=headers,
            timeout=timeout,
        )
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_owns_client", self.client is None)

        object.__setattr__(self, "_search_path", _normalize_path(self.search_path))
        object.__setattr__(self, "_health_path", _normalize_path(self.health_path))

    name = "slskd"

    async def aclose(self) -> None:
        if getattr(self, "_owns_client", False):
            await self._client.aclose()

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        trimmed_query = query.text.strip()
        if not trimmed_query:
            raise ProviderValidationError(self.name, "query must not be empty", status_code=400)

        normalized_query = _normalise_search_value(trimmed_query)
        normalized_artist = _normalise_search_value(query.artist) if query.artist else None
        combined = _combine_terms(normalized_query, normalized_artist)
        if not combined:
            raise ProviderValidationError(
                self.name,
                "query must not be empty after normalization",
                status_code=400,
            )

        effective_limit = max(1, min(int(query.limit), self._max_results))
        params = {"query": combined, "limit": effective_limit, "type": "track"}

        try:
            response = await self._client.get(
                self._search_path, params=params, headers=self._headers
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.name, self._timeout_ms, cause=exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderDependencyError(self.name, "slskd request failed", cause=exc) from exc

        status_code = response.status_code
        if status_code == httpx.codes.OK:
            try:
                payload = response.json()
            except ValueError as exc:  # pragma: no cover - defensive guard
                raise ProviderInternalError(
                    self.name, "slskd returned invalid JSON", cause=exc
                ) from exc
            candidates = [_build_candidate(entry) for entry in _iter_files(payload)]
            if not candidates:
                raise ProviderNotFoundError(self.name, "slskd returned no results", status_code=404)
            ranked = _sort_candidates(candidates, self._format_ranking)
            limited = ranked[:effective_limit]
            return [normalize_slskd_track(candidate, provider=self.name) for candidate in limited]

        if status_code in {httpx.codes.BAD_REQUEST, httpx.codes.UNPROCESSABLE_ENTITY}:
            raise ProviderValidationError(
                self.name, "slskd rejected the search request", status_code=status_code
            )

        if status_code == httpx.codes.TOO_MANY_REQUESTS:
            retry_after = _parse_retry_after_ms(response.headers)
            raise ProviderRateLimitedError(
                self.name,
                "slskd rate limited the request",
                retry_after_ms=retry_after,
                retry_after_header=response.headers.get("Retry-After"),
                status_code=status_code,
            )

        if status_code == httpx.codes.NOT_FOUND:
            raise ProviderNotFoundError(
                self.name, "slskd returned no results", status_code=status_code
            )

        if 500 <= status_code < 600:
            raise ProviderDependencyError(
                self.name, "slskd dependency error", status_code=status_code
            )

        raise ProviderInternalError(
            self.name, f"slskd responded with an unexpected status ({status_code})"
        )

    async def fetch_artist(
        self, *, artist_id: str | None = None, name: str | None = None
    ) -> ProviderArtist | None:
        identifier = (artist_id or "").strip()
        query_name = (name or "").strip()
        artist_name = query_name or identifier
        if not artist_name:
            raise ProviderValidationError(
                self.name,
                "artist_id or name must be provided",
                status_code=400,
            )

        search_query = SearchQuery(text=artist_name, artist=artist_name, limit=1)
        tracks = await self.search_tracks(search_query)
        if not tracks:
            raise ProviderNotFoundError(self.name, "artist not found", status_code=404)

        primary_track = tracks[0]
        metadata = dict(primary_track.metadata or {})
        payload: dict[str, Any] = {
            "id": identifier or artist_name,
            "name": artist_name,
            "metadata": dict(metadata),
        }

        genres = metadata.get("genres")
        if isinstance(genres, list | tuple):
            payload["genres"] = [str(item) for item in genres if item]
        elif genres:
            payload["genres"] = [str(genres)]
        genre = metadata.get("genre")
        if genre and "genres" not in payload:
            payload["genre"] = str(genre)

        aliases: list[str] = []
        for track in tracks:
            for artist in track.artists:
                candidate = artist.name.strip()
                if candidate and candidate.lower() != artist_name.lower():
                    aliases.append(candidate)
        if aliases:
            payload["aliases"] = aliases

        try:
            return from_slskd_artist(payload)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ProviderInternalError(self.name, "invalid artist payload") from exc

    async def fetch_artist_releases(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderRelease]:
        identifier = (artist_source_id or "").strip()
        if not identifier:
            raise ProviderValidationError(
                self.name,
                "artist_source_id must not be empty",
                status_code=400,
            )

        try:
            max_items = max(1, int(limit)) if limit is not None else None
        except (TypeError, ValueError):
            max_items = None

        search_limit = max_items or self._max_results
        search_query = SearchQuery(text=identifier, artist=identifier, limit=search_limit)
        tracks = await self.search_tracks(search_query)
        if not tracks:
            return []

        releases: dict[str, ProviderRelease] = {}
        for track in tracks:
            album_payload: dict[str, Any] = {}
            if track.album is not None and track.album.name:
                album_payload["name"] = track.album.name
                if track.album.id:
                    album_payload["id"] = track.album.id
                if track.album.metadata:
                    album_payload["metadata"] = dict(track.album.metadata)
                    for key, value in track.album.metadata.items():
                        if key not in album_payload:
                            album_payload[key] = value

            track_metadata = dict(track.metadata or {})
            if not album_payload.get("name") and track_metadata.get("album"):
                album_payload["name"] = str(track_metadata["album"])
            if track_metadata.get("year") and "release_date" not in album_payload:
                album_payload["release_date"] = str(track_metadata["year"])

            if "metadata" in album_payload:
                combined_metadata = dict(album_payload["metadata"])
                combined_metadata.update(
                    {k: v for k, v in track_metadata.items() if k not in combined_metadata}
                )
                album_payload["metadata"] = combined_metadata
            elif track_metadata:
                album_payload["metadata"] = dict(track_metadata)

            if not album_payload.get("name"):
                continue

            try:
                release = from_slskd_release(album_payload, identifier)
            except ValueError:
                continue

            key = release.source_id or release.title
            if key in releases:
                continue
            releases[key] = release
            if max_items is not None and len(releases) >= max_items:
                break

        return list(releases.values())

    async def fetch_album(self, album_source_id: str) -> ProviderAlbumDetails | None:
        identifier = (album_source_id or "").strip()
        if not identifier:
            raise ProviderValidationError(
                self.name,
                "album_source_id must not be empty",
                status_code=400,
            )

        search_limit = self._max_results
        search_query = SearchQuery(text=identifier, artist=identifier, limit=search_limit)
        tracks = await self.search_tracks(search_query)
        if not tracks:
            raise ProviderNotFoundError(self.name, "album not found", status_code=404)

        payload: dict[str, Any] = {"id": identifier, "title": identifier}
        metadata: dict[str, Any] = {}
        release_candidates: list[str] = []
        total_candidates: list[int] = []
        genre_candidates: set[str] = set()

        for track in tracks:
            if track.album and track.album.name and payload.get("title") == identifier:
                payload["title"] = track.album.name
            if track.album and track.album.id and payload.get("id") == identifier:
                payload["id"] = track.album.id
            if track.album and track.album.metadata:
                for key, value in track.album.metadata.items():
                    metadata.setdefault(key, value)
            if track.album and track.album.release_date:
                release_candidates.append(track.album.release_date)
            if track.album and track.album.total_tracks is not None:
                total_candidates.append(track.album.total_tracks)

            track_metadata = dict(track.metadata or {})
            if "release_date" in track_metadata:
                release_candidates.append(str(track_metadata["release_date"]))
            if "year" in track_metadata:
                release_candidates.append(str(track_metadata["year"]))
            if "total_tracks" in track_metadata:
                candidate_total = _coerce_int(track_metadata["total_tracks"])
                if candidate_total is not None:
                    total_candidates.append(candidate_total)
            if "genre" in track_metadata:
                genre_candidates.add(str(track_metadata["genre"]))

        if metadata:
            payload["metadata"] = metadata
        if release_candidates:
            payload["release_date"] = release_candidates[0]
        if total_candidates:
            payload["total_tracks"] = max(total_candidates)
        if genre_candidates:
            payload["genre"] = sorted(genre_candidates)[0]

        return from_slskd_album_details(payload, tracks=tracks, provider=self.name)

    async def fetch_artist_top_tracks(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderTrack]:
        identifier = (artist_source_id or "").strip()
        if not identifier:
            raise ProviderValidationError(
                self.name,
                "artist_source_id must not be empty",
                status_code=400,
            )

        try:
            max_items = max(1, int(limit)) if limit is not None else None
        except (TypeError, ValueError):
            max_items = None

        effective_limit = max_items or self._max_results
        search_query = SearchQuery(text=identifier, artist=identifier, limit=effective_limit)
        tracks = await self.search_tracks(search_query)
        if max_items is not None:
            return tracks[:max_items]
        return tracks

    async def check_health(self) -> Mapping[str, Any]:
        try:
            response = await self._client.get(self._health_path, headers=self._headers)
        except httpx.TimeoutException:
            return {"status": "degraded", "details": {"reason": "timeout"}}
        except httpx.HTTPError as exc:  # pragma: no cover - defensive guard
            return {"status": "down", "details": {"error": str(exc)}}

        status_code = response.status_code
        if status_code >= 500:
            return {"status": "down", "details": {"status_code": status_code}}
        if status_code >= 400:
            return {"status": "degraded", "details": {"status_code": status_code}}
        return {"status": "ok", "details": {"status_code": status_code}}


__all__ = ["SlskdAdapter"]
