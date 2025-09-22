"""Async Plex client built on top of the public Plex API."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List

import aiohttp

from app.config import PlexConfig
from app.logging import get_logger

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
            "POST", path, params=params, data=data, json_body=json_body, expect_json=expect_json
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

    async def get_library_items(
        self, section_id: str, params: Dict[str, Any] | None = None
    ) -> Any:
        """Return items for a given library section."""

        return await self._get(f"/library/sections/{section_id}/all", params=params)

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

    async def get_devices(self) -> Any:
        return await self._get("/devices")

    async def get_dvr(self) -> Any:
        return await self._get("/livetv/dvrs")

    async def get_live_tv(self, params: Dict[str, Any] | None = None) -> Any:
        return await self._get("/livetv", params=params)

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
            section_container = (
                items.get("MediaContainer", {}) if isinstance(items, dict) else {}
            )
            stats["artists"] += int(section_container.get("totalSize", 0))

            albums = await self.get_library_items(section_id, params={"type": "9"})
            album_container = (
                albums.get("MediaContainer", {}) if isinstance(albums, dict) else {}
            )
            stats["albums"] += int(album_container.get("totalSize", 0))

            tracks = await self.get_library_items(section_id, params={"type": "8"})
            track_container = (
                tracks.get("MediaContainer", {}) if isinstance(tracks, dict) else {}
            )
            stats["tracks"] += int(track_container.get("totalSize", 0))
        return stats

    @asynccontextmanager
    async def listen_notifications(self) -> AsyncIterator[aiohttp.ClientWebSocketResponse]:
        """Connect to the Plex websocket notification endpoint."""

        session = await self._ensure_session()
        url = self._build_url("/:/websocket/notifications")
        headers = self._build_headers()
        async with session.ws_connect(url, headers=headers) as websocket:
            yield websocket

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

