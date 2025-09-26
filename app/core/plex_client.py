"""Async Plex client built on top of the public Plex API."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import aiohttp

from app.config import PlexConfig
from app.logging import get_logger
from app.utils.metadata_utils import extract_metadata_from_plex

logger = get_logger(__name__)


class PlexClientError(RuntimeError):
    """Raised when the Plex API returns an error response."""


class PlexClient:
    """Asynchronous Plex API wrapper.

    The client intentionally exposes only the pieces of the API that are
    required by Harmony.  All HTTP communication is performed with
    :mod:`aiohttp` and a very small retry helper is used to increase
    robustness when Plex temporarily fails to respond.
    """

    _DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
    _RETRY_ATTEMPTS = 3
    _RETRY_BASE_DELAY = 0.25

    def __init__(self, config: PlexConfig) -> None:
        if not (config.base_url and config.token):
            raise ValueError("Plex configuration is incomplete")
        self._base_url = config.base_url.rstrip("/")
        self._token = config.token
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        async with self._lock:
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
        attempt = 0
        last_exception: Exception | None = None
        while attempt < self._RETRY_ATTEMPTS:
            attempt += 1
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
                        raise PlexClientError(
                            f"Plex {method} {url} failed with status {response.status}: {text}"
                        )
                    if expect_json:
                        return await response.json(content_type=None)
                    return await response.text()
            except Exception as exc:  # pragma: no cover - defensive logging
                last_exception = exc
                logger.warning(
                    "Plex request error (%s %s attempt %d/%d): %s",
                    method,
                    url,
                    attempt,
                    self._RETRY_ATTEMPTS,
                    exc,
                )
                if attempt >= self._RETRY_ATTEMPTS:
                    break
                await asyncio.sleep(self._RETRY_BASE_DELAY * attempt)
        assert last_exception is not None
        raise last_exception

    async def _get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

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

    async def _put(
        self,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("PUT", path, params=params, data=data, json_body=json_body)

    async def _delete(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        return await self._request("DELETE", path, params=params)

    async def get_libraries(self, params: Dict[str, Any] | None = None) -> Any:
        """Return all Plex library sections."""

        return await self._get("/library/sections", params=params)

    async def get_library_items(self, section_id: str, params: Dict[str, Any] | None = None) -> Any:
        """Return items for a given library section."""

        return await self._get(f"/library/sections/{section_id}/all", params=params)

    async def refresh_library_section(self, section_id: str, *, full: bool = False) -> None:
        """Trigger a Plex library scan for the given section."""

        params = {"force": int(bool(full))}
        await self._request(
            "GET",
            f"/library/sections/{section_id}/refresh",
            params=params,
            expect_json=False,
        )

    async def get_metadata(self, item_id: str) -> Any:
        return await self._get(f"/library/metadata/{item_id}")

    async def get_sessions(self) -> Any:
        return await self._get("/status/sessions")

    async def get_session_history(self, params: Dict[str, Any] | None = None) -> Any:
        return await self._get("/status/sessions/history/all", params=params)

    async def get_timeline(self, params: Dict[str, Any] | None = None) -> Any:
        return await self._get("/:/timeline", params=params)

    async def update_timeline(self, data: Dict[str, Any]) -> Any:
        return await self._post("/:/timeline", data=data, expect_json=False)

    async def scrobble(self, data: Dict[str, Any]) -> Any:
        return await self._post("/:/scrobble", data=data, expect_json=False)

    async def unscrobble(self, data: Dict[str, Any]) -> Any:
        return await self._post("/:/unscrobble", data=data, expect_json=False)

    async def get_playlists(self) -> Any:
        return await self._get("/playlists")

    async def create_playlist(self, payload: Dict[str, Any]) -> Any:
        return await self._post("/playlists", json_body=payload)

    async def update_playlist(self, playlist_id: str, payload: Dict[str, Any]) -> Any:
        return await self._put(f"/playlists/{playlist_id}", json_body=payload)

    async def delete_playlist(self, playlist_id: str) -> Any:
        return await self._delete(f"/playlists/{playlist_id}")

    async def create_playqueue(self, payload: Dict[str, Any]) -> Any:
        return await self._post("/playQueues", json_body=payload)

    async def get_playqueue(self, playqueue_id: str) -> Any:
        return await self._get(f"/playQueues/{playqueue_id}")

    async def rate_item(self, item_id: str, rating: int) -> Any:
        payload = {"key": item_id, "rating": rating}
        return await self._post("/:/rate", data=payload, expect_json=False)

    async def sync_tags(self, item_id: str, tags: Dict[str, List[str]]) -> Any:
        payload = {"key": item_id, **tags}
        return await self._post("/:/settags", json_body=payload)

    async def get_track_metadata(self, item_id: str) -> Dict[str, Any]:
        try:
            payload = await self.get_metadata(item_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Plex metadata lookup failed for %s: %s", item_id, exc)
            return {}

        entry = self._extract_metadata_entry(payload)
        if entry is None:
            return {}

        return extract_metadata_from_plex(entry)

    async def get_devices(self) -> Any:
        return await self._get("/devices")

    async def get_dvr(self) -> Any:
        return await self._get("/livetv/dvrs")

    async def get_live_tv(self, params: Dict[str, Any] | None = None) -> Any:
        return await self._get("/livetv", params=params)

    async def search_music(
        self,
        query: str,
        *,
        section_id: str | None = None,
        mediatypes: Sequence[str] | None = None,
        limit: int = 50,
        genre: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> List[Dict[str, Any]]:
        """Search the Plex music library for artists, albums or tracks."""

        library_section = section_id or await self._default_music_section()
        if not library_section:
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

        type_codes: list[str] = []
        for mediatype in mediatypes or []:
            mapped = self._map_media_type(mediatype)
            if mapped:
                type_codes.append(mapped)
        if type_codes:
            params["type"] = ",".join(type_codes)

        payload = await self.get_library_items(library_section, params=params)
        return self._extract_search_entries(payload)

    async def _default_music_section(self) -> Optional[str]:
        libraries = await self.get_libraries()
        if not isinstance(libraries, dict):
            return None
        container = libraries.get("MediaContainer")
        if not isinstance(container, dict):
            return None
        for directory in container.get("Directory", []):
            if not isinstance(directory, dict):
                continue
            if directory.get("type") == "artist":
                key = directory.get("key")
                if key:
                    return str(key)
        return None

    def _map_media_type(self, mediatype: str | None) -> Optional[str]:
        if not mediatype:
            return None
        lowered = str(mediatype).strip().lower()
        if lowered in self._MUSIC_TYPE_MAP:
            return self._MUSIC_TYPE_MAP[lowered]
        if lowered in {"8", "9", "10"}:
            return lowered
        return None

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

    @classmethod
    def normalise_music_entry(cls, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Return a simplified representation of a Plex metadata entry."""

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
        if lowered == "1" or lowered == "artist":
            return "artist"
        if lowered == "2" or lowered == "album":
            return "album"
        if lowered == "4" or lowered == "track":
            return "track"
        return "track"

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

    async def get_library_statistics(self) -> Dict[str, int]:
        """Compute high level statistics for the Plex music library."""

        stats = {"artists": 0, "albums": 0, "tracks": 0}
        libraries = await self.get_libraries()
        container = libraries.get("MediaContainer", {}) if isinstance(libraries, dict) else {}
        for section in container.get("Directory", []):
            if section.get("type") != "artist":
                continue
            section_id = section.get("key")
            if not section_id:
                continue
            items = await self.get_library_items(section_id, params={"type": "10"})
            section_container = items.get("MediaContainer", {}) if isinstance(items, dict) else {}
            stats["artists"] += int(section_container.get("totalSize", 0))

            albums = await self.get_library_items(section_id, params={"type": "9"})
            album_container = albums.get("MediaContainer", {}) if isinstance(albums, dict) else {}
            stats["albums"] += int(album_container.get("totalSize", 0))

            tracks = await self.get_library_items(section_id, params={"type": "8"})
            track_container = tracks.get("MediaContainer", {}) if isinstance(tracks, dict) else {}
            stats["tracks"] += int(track_container.get("totalSize", 0))
        return stats

    @asynccontextmanager
    async def listen_notifications(
        self,
    ) -> AsyncIterator[aiohttp.ClientWebSocketResponse]:
        """Connect to the Plex websocket notification endpoint."""

        session = await self._ensure_session()
        url = self._build_url("/:/websocket/notifications")
        headers = self._build_headers()
        async with session.ws_connect(url, headers=headers) as websocket:
            yield websocket

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    _MUSIC_TYPE_MAP = {"track": "10", "album": "9", "artist": "8"}
