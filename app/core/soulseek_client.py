"""Async client for the slskd REST API."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Dict, Optional

import aiohttp

from app.config import SoulseekConfig
from app.logging import get_logger


logger = get_logger(__name__)


class SoulseekClientError(RuntimeError):
    pass


class SoulseekClient:
    RATE_LIMIT_COUNT = 35
    RATE_LIMIT_WINDOW = 220.0

    def __init__(
        self,
        config: SoulseekConfig,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._config = config
        self._session = session
        self._session_owner = session is None
        self._timestamps: deque[float] = deque(maxlen=self.RATE_LIMIT_COUNT)
        self._lock = asyncio.Lock()
        self._max_retries = 3

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _build_url(self, path: str) -> str:
        base = self._config.base_url.rstrip("/")
        return f"{base}/api/v0/{path.lstrip('/')}"

    def _build_headers(self) -> Dict[str, str]:
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

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        await self._respect_rate_limit()
        session = await self._ensure_session()
        url = self._build_url(path)
        headers = kwargs.pop("headers", {})
        headers = {**self._build_headers(), **headers}

        backoff = 0.5
        for attempt in range(1, self._max_retries + 1):
            try:
                async with session.request(method, url, headers=headers, **kwargs) as response:
                    if response.status >= 400:
                        content = await response.text()
                        raise SoulseekClientError(
                            f"slskd error {response.status}: {content[:200]}"
                        )
                    if "application/json" in response.headers.get("Content-Type", ""):
                        return await response.json()
                    return await response.text()
            except (aiohttp.ClientError, SoulseekClientError) as exc:
                if attempt == self._max_retries:
                    logger.error("Soulseek request failed: %s", exc)
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2

    async def close(self) -> None:
        if self._session_owner and self._session and not self._session.closed:
            await self._session.close()

    async def search(self, query: str) -> Dict[str, Any]:
        payload = {"searchText": query, "filterResponses": True}
        return await self._request("POST", "searches", json=payload)

    async def download(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        username = payload.get("username")
        if not username:
            raise ValueError("username is required for download requests")
        downloads = payload.get("files")
        if not isinstance(downloads, list) or not downloads:
            raise ValueError("files must be a non-empty list")
        return await self._request("POST", f"transfers/downloads/{username}", json=downloads)

    async def get_download_status(self) -> Dict[str, Any]:
        return await self._request("GET", "transfers/downloads")

    async def cancel_download(self, download_id: str) -> Dict[str, Any]:
        return await self._request("DELETE", f"transfers/downloads/{download_id}")
