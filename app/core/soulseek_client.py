"""Async client for the slskd REST API."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
import json
from pathlib import Path
import time
from typing import Any

import aiohttp

from app.config import SoulseekConfig
from app.logging import get_logger
from app.utils.retry import RetryDirective, with_retry

logger = get_logger(__name__)


class SoulseekClientError(RuntimeError):
    """Raised when slskd returns an error or cannot be reached."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class SoulseekClient:
    RATE_LIMIT_COUNT = 35
    RATE_LIMIT_WINDOW = 220.0

    def __init__(
        self,
        config: SoulseekConfig,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._config = config
        self._session = session
        self._session_owner = session is None
        self._timestamps: deque[float] = deque(maxlen=self.RATE_LIMIT_COUNT)
        self._lock = asyncio.Lock()
        self._retry_attempts = max(1, int(config.retry_max) + 1)
        self._retry_backoff_base_ms = max(1, int(config.retry_backoff_base_ms))
        self._retry_jitter_pct = self._resolve_jitter_pct(config.retry_jitter_pct)
        self._timeout_ms = max(0, int(config.timeout_ms))

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _build_url(self, path: str) -> str:
        base = self._config.base_url.rstrip("/")
        return f"{base}/api/v0/{path.lstrip('/')}"

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["X-API-Key"] = self._config.api_key
        return headers

    async def _respect_rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > self.RATE_LIMIT_WINDOW:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.RATE_LIMIT_COUNT:
                wait_time = self.RATE_LIMIT_WINDOW - (now - self._timestamps[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            self._timestamps.append(time.monotonic())

    @staticmethod
    def _resolve_jitter_pct(value: float) -> int:
        jitter = max(0.0, float(value))
        if jitter <= 1:
            return int(round(jitter * 100))
        return int(round(jitter))

    @staticmethod
    def _should_retry(error: SoulseekClientError) -> bool:
        status = error.status_code
        if status is None:
            return True
        if status >= 500:
            return True
        if status in {408, 429}:
            return True
        return False

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        await self._respect_rate_limit()
        session = await self._ensure_session()
        url = self._build_url(path)
        headers = kwargs.pop("headers", {})
        headers = {**self._build_headers(), **headers}

        async def _perform_request() -> Any:
            try:
                async with session.request(method, url, headers=headers, **kwargs) as response:
                    content_type = response.headers.get("Content-Type", "")
                    body_text = await response.text()
                    if response.status >= 400:
                        payload: Any | None = None
                        if "application/json" in content_type:
                            try:
                                payload = json.loads(body_text)
                            except json.JSONDecodeError:
                                payload = None
                        raise SoulseekClientError(
                            f"slskd error {response.status}: {body_text[:200]}",
                            status_code=response.status,
                            payload=payload,
                        )
                    if "application/json" in content_type:
                        if not body_text:
                            return {}
                        try:
                            return json.loads(body_text)
                        except json.JSONDecodeError as decode_error:
                            raise SoulseekClientError(
                                "slskd returned invalid JSON",
                                status_code=response.status,
                            ) from decode_error
                    return body_text
            except aiohttp.ClientResponseError as exc:
                raise SoulseekClientError(str(exc), status_code=exc.status) from exc
            except aiohttp.ClientError as exc:
                raise SoulseekClientError(str(exc)) from exc

        def _classify(exc: Exception) -> RetryDirective:
            if isinstance(exc, asyncio.TimeoutError):
                message = (
                    f"slskd request timed out after {self._timeout_ms}ms"
                    if self._timeout_ms > 0
                    else "slskd request timed out"
                )
                error = SoulseekClientError(message, status_code=408)
            elif isinstance(exc, SoulseekClientError):
                error = exc
            else:
                error = SoulseekClientError(str(exc))
            should_retry = self._should_retry(error)
            return RetryDirective(retry=should_retry, error=error)

        timeout_ms = self._timeout_ms if self._timeout_ms > 0 else None

        try:
            return await with_retry(
                _perform_request,
                attempts=self._retry_attempts,
                base_ms=self._retry_backoff_base_ms,
                jitter_pct=self._retry_jitter_pct,
                timeout_ms=timeout_ms,
                classify_err=_classify,
            )
        except SoulseekClientError as exc:
            logger.error("Soulseek request failed: %s", exc)
            raise

    async def close(self) -> None:
        if self._session_owner and self._session and not self._session.closed:
            await self._session.close()

    async def search(
        self,
        query: str,
        *,
        min_bitrate: int | None = None,
        format_priority: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"searchText": query, "filterResponses": True}
        if min_bitrate is not None:
            payload["minBitrate"] = int(min_bitrate)
        if format_priority:
            payload["preferredFormats"] = list(format_priority)
        return await self._request("POST", "searches", json=payload)

    async def download(self, payload: dict[str, Any]) -> dict[str, Any]:
        username = payload.get("username")
        if not username:
            raise ValueError("username is required for download requests")
        downloads = payload.get("files")
        if not isinstance(downloads, list) or not downloads:
            raise ValueError("files must be a non-empty list")
        return await self._request("POST", f"transfers/downloads/{username}", json=downloads)

    async def get_download_status(self) -> dict[str, Any]:
        return await self._request("GET", "transfers/downloads")

    async def cancel_download(self, download_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"transfers/downloads/{download_id}")

    async def get_download(self, download_id: str) -> dict[str, Any]:
        return await self._request("GET", f"transfers/downloads/{download_id}")

    async def get_all_downloads(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "transfers/downloads/all")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "downloads" in result:
            payload = result["downloads"]
            return payload if isinstance(payload, list) else [payload]
        return [result]

    async def remove_completed_downloads(self) -> dict[str, Any]:
        return await self._request("DELETE", "transfers/downloads/completed")

    async def get_queue_position(self, download_id: str) -> dict[str, Any]:
        return await self._request("GET", f"transfers/downloads/{download_id}/queue")

    async def get_download_metadata(self, download_id: str) -> dict[str, Any]:
        try:
            payload = await self.get_download(download_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to fetch download metadata for %s: %s", download_id, exc)
            return {}

        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        if not isinstance(metadata, dict):
            return {}
        normalised: dict[str, Any] = {}
        for key, value in metadata.items():
            if value in {None, ""}:
                continue
            normalised[str(key)] = value
        return normalised

    async def enqueue(self, username: str, files: list[dict[str, Any]]) -> dict[str, Any]:
        if not username:
            raise ValueError("username is required for enqueue requests")
        if not isinstance(files, list) or not files:
            raise ValueError("files must be a non-empty list")
        payload = {"username": username, "files": files}
        return await self._request("POST", "transfers/enqueue", json=payload)

    async def cancel_upload(self, upload_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"transfers/uploads/{upload_id}")

    async def get_upload(self, upload_id: str) -> dict[str, Any]:
        return await self._request("GET", f"transfers/uploads/{upload_id}")

    async def get_uploads(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "transfers/uploads")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "uploads" in result:
            payload = result["uploads"]
            return payload if isinstance(payload, list) else [payload]
        return [result]

    async def get_all_uploads(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "transfers/uploads/all")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "uploads" in result:
            payload = result["uploads"]
            return payload if isinstance(payload, list) else [payload]
        return [result]

    async def remove_completed_uploads(self) -> dict[str, Any]:
        return await self._request("DELETE", "transfers/uploads/completed")

    async def user_address(self, username: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{username}/address")

    async def user_browse(self, username: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{username}/browse")

    async def user_browsing_status(self, username: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{username}/browsing-status")

    async def user_directory(self, username: str, path: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{username}/directory", params={"path": path})

    async def user_info(self, username: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{username}/info")

    async def user_status(self, username: str) -> dict[str, Any]:
        return await self._request("GET", f"users/{username}/status")

    @staticmethod
    def _normalise_username(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    def normalise_search_results(self, payload: Any) -> list[dict[str, Any]]:
        """Flatten the raw search payload returned by slskd."""

        if payload is None:
            return []

        if isinstance(payload, dict):
            results = payload.get("results") or payload.get("matches") or []
            if isinstance(results, list):
                entries = results
            elif isinstance(results, dict):
                entries = [results]
            else:
                entries = []
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []

        normalised: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            username = self._normalise_username(entry.get("username"))
            files = entry.get("files") or []
            if isinstance(files, dict):
                files = files.values()
            for file_info in files:
                if not isinstance(file_info, dict):
                    continue
                normalised.append(self._normalise_file(username, file_info))
        return normalised

    @staticmethod
    def _normalise_file(username: str | None, file_info: dict[str, Any]) -> dict[str, Any]:
        identifier = (
            file_info.get("id")
            or file_info.get("token")
            or file_info.get("path")
            or file_info.get("filename")
        )
        item_id = str(identifier) if identifier is not None else None

        filename = str(file_info.get("filename") or file_info.get("path") or "")
        title = str(file_info.get("title") or filename)
        artist_value = file_info.get("artist") or file_info.get("artists")
        if isinstance(artist_value, list):
            artists = [str(item) for item in artist_value if item]
        elif artist_value:
            artists = [str(artist_value)]
        else:
            artists = []
        album = file_info.get("album")
        album_title = str(album) if album else None

        bitrate_value = file_info.get("bitrate")
        bitrate: int | None = None
        if isinstance(bitrate_value, int | float):
            bitrate = int(bitrate_value)
        elif isinstance(bitrate_value, str) and bitrate_value.isdigit():
            bitrate = int(bitrate_value)

        format_value = file_info.get("format") or file_info.get("extension")
        if not format_value and filename:
            format_value = Path(filename).suffix.lstrip(".")
        audio_format = str(format_value).lower() if format_value else None
        if not audio_format and filename:
            lowered = filename.lower()
            for marker, resolved in (
                ("flac", "flac"),
                ("alac", "alac"),
                ("wav", "wav"),
                ("aiff", "aiff"),
                ("aac", "aac"),
            ):
                if marker in lowered:
                    audio_format = resolved
                    break

        duration_value = (
            file_info.get("duration_ms") or file_info.get("duration") or file_info.get("length")
        )
        duration_ms: int | None = None
        if isinstance(duration_value, int | float):
            duration_ms = int(duration_value)
        elif isinstance(duration_value, str) and duration_value.isdigit():
            duration_ms = int(duration_value)

        year_value = file_info.get("year") or file_info.get("date")
        year: int | None = None
        if isinstance(year_value, int):
            year = year_value
        elif isinstance(year_value, str) and year_value.isdigit():
            year = int(year_value)

        genre_value = file_info.get("genre") or file_info.get("genres")
        if isinstance(genre_value, list):
            genres = [str(item) for item in genre_value if item]
        elif genre_value:
            genres = [str(genre_value)]
        else:
            genres = []

        size_value = file_info.get("size")
        if isinstance(size_value, int | float):
            size = int(size_value)
        elif isinstance(size_value, str) and size_value.isdigit():
            size = int(size_value)
        else:
            size = None

        if bitrate is None:
            if audio_format in {"flac", "alac", "wav", "aiff"}:
                bitrate = 1000
            elif filename:
                lowered = filename.lower()
                if "320" in lowered:
                    bitrate = 320
                elif "256" in lowered:
                    bitrate = 256

        return {
            "id": item_id,
            "title": title,
            "artists": artists,
            "album": album_title,
            "year": year,
            "duration_ms": duration_ms,
            "bitrate": bitrate,
            "format": audio_format,
            "genres": genres,
            "extra": {
                "username": username,
                "path": file_info.get("path") or filename,
                "size": size,
                "availability": file_info.get("availability"),
            },
        }
