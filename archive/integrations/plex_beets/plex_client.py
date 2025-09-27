"""Async Plex client tailored for lean matching and scan operations."""

from __future__ import annotations

import asyncio
import random
from http import HTTPStatus
from typing import Any, Dict, Iterable, List, Optional

import aiohttp

from app.config import PlexConfig
from app.logging import get_logger
from app.utils.metadata_utils import extract_metadata_from_plex

logger = get_logger(__name__)


class PlexClientError(RuntimeError):
    """Base class for Plex client failures."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status


class PlexClientAuthError(PlexClientError):
    """Raised when Plex reports an authentication error."""


class PlexClientNotFoundError(PlexClientError):
    """Raised when a requested resource does not exist on the Plex server."""


class PlexClientRateLimitedError(PlexClientError):
    """Raised when Plex responds with a rate limit status code."""


class PlexClient:
    """Minimal asynchronous Plex API wrapper."""

    _DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)
    _RETRY_ATTEMPTS = 3
    _RETRY_BASE_DELAY = 0.35

    def __init__(self, config: PlexConfig) -> None:
        if not (config.base_url and config.token):
            raise ValueError("Plex configuration is incomplete")
        self._base_url = config.base_url.rstrip("/")
        self._token = config.token
        self._library_override = (config.library_name or "").strip() or None
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._default_section: str | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=self._DEFAULT_TIMEOUT)
        assert self._session is not None
        return self._session

    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self._base_url}{path}"

    def _build_headers(self) -> Dict[str, str]:
        return {"X-Plex-Token": self._token}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        url = self._build_url(path)
        attempt = 1
        while attempt <= self._RETRY_ATTEMPTS:
            session = await self._ensure_session()
            try:
                async with session.request(
                    method,
                    url,
                    headers=self._build_headers(),
                    params=params,
                    data=data,
                    json=json_body,
                ) as response:
                    if response.status >= 400:
                        text = await response.text()
                        self._raise_for_status(method, url, response.status, text)
                    if expect_json:
                        return await response.json(content_type=None)
                    return await response.text()
            except PlexClientError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt >= self._RETRY_ATTEMPTS:
                    raise PlexClientError(
                        f"Plex request {method} {url} failed after retries: {exc}",
                    ) from exc
                delay = self._retry_delay(attempt)
                logger.debug(
                    "Retrying Plex request %s %s in %.2fs due to %s",
                    method,
                    url,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                attempt += 1
        raise PlexClientError(f"Plex request {method} {url} exhausted retries")

    def _retry_delay(self, attempt: int) -> float:
        jitter = random.uniform(0.85, 1.15)
        return self._RETRY_BASE_DELAY * attempt * jitter

    def _raise_for_status(self, method: str, url: str, status: int, body: str) -> None:
        message = f"Plex {method} {url} failed with status {status}: {body.strip()[:256]}"
        if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            raise PlexClientAuthError(message, status=status)
        if status == HTTPStatus.NOT_FOUND:
            raise PlexClientNotFoundError(message, status=status)
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            raise PlexClientRateLimitedError(message, status=status)
        raise PlexClientError(message, status=status)

    async def _get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _get_text(self, path: str, params: Dict[str, Any] | None = None) -> str:
        return await self._request("GET", path, params=params, expect_json=False)

    async def _post(
        self,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        return await self._request(
            "POST",
            path,
            params=params,
            data=data,
            json_body=json_body,
            expect_json=expect_json,
        )

    async def get_status(self) -> Dict[str, Any]:
        """Return a lightweight status payload describing the Plex server."""

        identity: Dict[str, Any] = {}
        try:
            identity = await self._get("/identity")
        except PlexClientNotFoundError:  # pragma: no cover - defensive
            logger.debug("Plex identity endpoint unavailable")

        libraries = await self.get_libraries()
        library_count = 0
        if isinstance(libraries, dict):
            container = libraries.get("MediaContainer")
            if isinstance(container, dict):
                directory_field = container.get("Directory")
                if isinstance(directory_field, list):
                    library_count = len(
                        [entry for entry in directory_field if isinstance(entry, dict)]
                    )

        identity_container = identity.get("MediaContainer") if isinstance(identity, dict) else {}
        server_name = "Plex"
        server_version = ""
        if isinstance(identity_container, dict):
            server_name = str(
                identity_container.get("friendlyName")
                or identity_container.get("name")
                or server_name
            )
            server_version = str(identity_container.get("version") or "")

        return {
            "server": {"name": server_name, "version": server_version},
            "libraries": library_count,
        }

    async def get_libraries(self, params: Dict[str, Any] | None = None) -> Any:
        """Return the raw Plex libraries payload."""

        return await self._get("/library/sections", params=params)

    async def get_library_items(self, section_id: str, params: Dict[str, Any] | None = None) -> Any:
        """Return items within a library section."""

        return await self._get(f"/library/sections/{section_id}/all", params=params)

    async def get_metadata(self, item_id: str) -> Any:
        return await self._get(f"/library/metadata/{item_id}")

    async def refresh_library_section(self, section_id: str, *, full: bool = False) -> None:
        params = {"force": int(bool(full))}
        await self._get_text(f"/library/sections/{section_id}/refresh", params=params)

    async def search_music(
        self,
        query: str,
        *,
        section_id: str | None = None,
        mediatypes: Iterable[str] | None = None,
        limit: int = 50,
        genre: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> List[Dict[str, Any]]:
        section = section_id or await self._default_music_section()
        if not section:
            return []

        params: Dict[str, Any] = {"query": query, "sort": "titleSort:asc"}
        if limit:
            params["limit"] = max(int(limit), 1)
        if genre:
            params["genre"] = genre
        if year_from is not None or year_to is not None:
            if year_from is not None and year_to is not None:
                params["year"] = f"{year_from}-{year_to}"
            elif year_from is not None:
                params["year"] = f">={year_from}"
            elif year_to is not None:
                params["year"] = f"<={year_to}"

        type_codes: List[str] = []
        for mediatype in mediatypes or []:
            mapped = self._map_media_type(mediatype)
            if mapped:
                type_codes.append(mapped)
        if type_codes:
            params["type"] = ",".join(type_codes)

        payload = await self.get_library_items(section, params=params)
        return self._extract_search_entries(payload)

    async def list_tracks(
        self,
        *,
        artist: str | None = None,
        album: str | None = None,
        section_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        section = section_id or await self._default_music_section()
        if not section:
            return []

        params = {
            "type": self._MUSIC_TYPE_MAP["track"],
            "includeGuids": 1,
            "sort": "track:asc",
        }
        payload = await self.get_library_items(section, params=params)
        entries = self._extract_search_entries(payload)

        compact: List[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if album and str(entry.get("parentTitle")) != album:
                continue
            if artist and str(entry.get("grandparentTitle")) != artist:
                continue
            rating_key = entry.get("ratingKey")
            if rating_key is None:
                continue
            track_number = entry.get("index") or entry.get("track")
            guid = ""
            guid_container = entry.get("Guid")
            if isinstance(guid_container, list) and guid_container:
                first_guid = guid_container[0]
                if isinstance(first_guid, dict):
                    guid = str(first_guid.get("id", ""))
            compact.append(
                {
                    "title": entry.get("title"),
                    "track": int(track_number) if isinstance(track_number, (int, float)) else 0,
                    "guid": guid,
                    "ratingKey": str(rating_key),
                    "section_id": entry.get("librarySectionID"),
                }
            )
        return compact

    async def get_library_statistics(self) -> Dict[str, int]:
        """Compute simple statistics for music libraries."""

        stats = {"artists": 0, "albums": 0, "tracks": 0}
        libraries = await self.get_libraries()
        container = libraries.get("MediaContainer", {}) if isinstance(libraries, dict) else {}
        sections = container.get("Directory") if isinstance(container, dict) else []
        for section in sections or []:
            if not isinstance(section, dict):
                continue
            if section.get("type") != "artist":
                continue
            section_id = section.get("key")
            if not section_id:
                continue
            for key, media_type in (("artists", "8"), ("albums", "9"), ("tracks", "10")):
                payload = await self.get_library_items(str(section_id), params={"type": media_type})
                section_container = (
                    payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}
                )
                size = section_container.get("totalSize")
                try:
                    stats[key] += int(size or 0)
                except (TypeError, ValueError):
                    stats[key] += 0
        return stats

    async def get_track_metadata(self, item_id: str) -> Dict[str, Any]:
        try:
            payload = await self.get_metadata(item_id)
        except PlexClientError as exc:  # pragma: no cover - defensive logging
            logger.debug("Plex metadata lookup failed for %s: %s", item_id, exc)
            return {}

        entry = self._extract_metadata_entry(payload)
        if entry is None:
            return {}
        return extract_metadata_from_plex(entry)

    async def _default_music_section(self) -> Optional[str]:
        if self._library_override:
            return self._library_override
        if self._default_section:
            return self._default_section
        libraries = await self.get_libraries()
        container = libraries.get("MediaContainer", {}) if isinstance(libraries, dict) else {}
        for directory in container.get("Directory", []) or []:
            if not isinstance(directory, dict):
                continue
            if directory.get("type") == "artist":
                key = directory.get("key")
                if key:
                    self._default_section = str(key)
                    return self._default_section
        return None

    async def default_music_section(self) -> Optional[str]:
        """Public helper returning the default music section id if available."""

        return await self._default_music_section()

    def _map_media_type(self, mediatype: str | None) -> Optional[str]:
        if not mediatype:
            return None
        lowered = str(mediatype).strip().lower()
        return self._MUSIC_TYPE_MAP.get(lowered, lowered if lowered.isdigit() else None)

    @staticmethod
    def _extract_search_entries(payload: Any) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        container = payload.get("MediaContainer")
        if isinstance(container, dict):
            metadata = container.get("Metadata")
            if isinstance(metadata, list):
                return [entry for entry in metadata if isinstance(entry, dict)]
        return []

    @staticmethod
    def _extract_metadata_entry(payload: Any) -> Dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        container = payload.get("MediaContainer")
        if isinstance(container, dict):
            metadata = container.get("Metadata")
            if isinstance(metadata, list) and metadata:
                first = metadata[0]
                if isinstance(first, dict):
                    return first
        return None

    @classmethod
    def normalise_music_entry(cls, entry: Dict[str, Any]) -> Dict[str, Any]:
        mediatype_raw = entry.get("type") or entry.get("metadataType")
        mediatype = cls._resolve_media_type(str(mediatype_raw) if mediatype_raw else "")

        title = str(entry.get("title") or "")
        album = str(entry.get("parentTitle") or entry.get("title") or "")
        artist_candidates: list[str] = []
        if mediatype == "track":
            artist_value = entry.get("grandparentTitle") or entry.get("originalTitle")
            if artist_value:
                artist_candidates.append(str(artist_value))
        elif mediatype == "album":
            artist_value = entry.get("parentTitle") or entry.get("grandparentTitle")
            if artist_value:
                artist_candidates.append(str(artist_value))
        elif mediatype == "artist" and title:
            artist_candidates.append(title)

        media = entry.get("Media")
        bitrate: Optional[int] = None
        audio_codec: Optional[str] = None
        if isinstance(media, list) and media:
            primary_media = media[0]
            if isinstance(primary_media, dict):
                bitrate_value = primary_media.get("bitrate")
                if isinstance(bitrate_value, (int, float)):
                    bitrate = int(bitrate_value)
                elif isinstance(bitrate_value, str) and bitrate_value.isdigit():
                    bitrate = int(bitrate_value)
                codec_value = primary_media.get("audioCodec") or primary_media.get("container")
                if codec_value:
                    audio_codec = str(codec_value).lower()

        raw_genres = entry.get("Genre") or entry.get("Genres")
        genres: list[str] = []
        if isinstance(raw_genres, list):
            for genre in raw_genres:
                if isinstance(genre, dict):
                    tag = genre.get("tag") or genre.get("label")
                    if tag:
                        genres.append(str(tag))

        duration_value = entry.get("duration")
        duration_ms: Optional[int] = None
        if isinstance(duration_value, (int, float)):
            duration_ms = int(duration_value)
        elif isinstance(duration_value, str) and duration_value.isdigit():
            duration_ms = int(duration_value)

        year_value = entry.get("year")
        year: Optional[int] = None
        if isinstance(year_value, int):
            year = year_value
        elif isinstance(year_value, str) and year_value.isdigit():
            year = int(year_value)

        return {
            "id": str(entry.get("ratingKey")) if entry.get("ratingKey") else None,
            "type": mediatype,
            "title": title,
            "album": album,
            "artists": artist_candidates,
            "year": year,
            "duration_ms": duration_ms,
            "bitrate": bitrate,
            "format": audio_codec,
            "genres": genres,
            "extra": {
                "ratingKey": entry.get("ratingKey"),
                "key": entry.get("key"),
                "librarySectionID": entry.get("librarySectionID"),
                "summary": entry.get("summary"),
            },
        }

    @classmethod
    def _resolve_media_type(cls, mediatype: str) -> str:
        lowered = mediatype.strip().lower()
        reverse_map = {value: key for key, value in cls._MUSIC_TYPE_MAP.items()}
        if lowered in reverse_map:
            return reverse_map[lowered]
        if lowered in cls._MUSIC_TYPE_MAP:
            return lowered
        if lowered in {"1", "artist"}:
            return "artist"
        if lowered in {"2", "album"}:
            return "album"
        return "track"

    _MUSIC_TYPE_MAP = {"track": "10", "album": "9", "artist": "8"}
