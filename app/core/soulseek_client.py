from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from app.config.settings import config_manager
from app.utils.logging_config import get_logger


logger = get_logger("soulseek_client")


@dataclass(slots=True)
class TrackResult:
    """Representation of a Soulseek track search response."""

    username: str
    filename: str
    size: int
    bitrate: Optional[int]
    duration: Optional[int]
    quality: str
    free_upload_slots: int
    upload_speed: int
    queue_length: int
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dictionary representation."""

        return asdict(self)


class SoulseekClient:
    """Async HTTP client that communicates with the slskd Soulseek daemon."""

    def __init__(self) -> None:
        self.base_url: Optional[str] = None
        self.api_key: Optional[str] = None
        self.download_path: Path = Path("./downloads")
        self.search_timestamps: List[float] = []
        self.max_searches_per_window = 35
        self.rate_limit_window = 220
        self._setup_client()

    def _setup_client(self) -> None:
        """Load configuration from the config manager and prepare the client."""

        config = config_manager.get_soulseek_config()
        self.base_url = config.get("slskd_url", "").rstrip("/") or None
        self.api_key = config.get("api_key") or None
        download_path_str = config.get("download_path", "./downloads")
        self.download_path = Path(download_path_str)
        self.download_path.mkdir(parents=True, exist_ok=True)
        logger.info("Soulseek client configured", extra={"base_url": self.base_url})

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def _make_request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            logger.error("Soulseek client not configured")
            return None

        url = f"{self.base_url}/api/v0/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method, url, headers=self._get_headers(), **kwargs
                ) as response:
                    if response.status in (200, 201):
                        return await response.json()

                    text = await response.text()
                    logger.error(
                        "Soulseek API request failed",
                        extra={
                            "method": method,
                            "url": url,
                            "status": response.status,
                            "body": text,
                        },
                    )
        except aiohttp.ClientError as exc:
            logger.error("Soulseek request error", exc_info=exc)
        except Exception as exc:  # pragma: no cover - safeguard for unexpected errors
            logger.error("Unexpected Soulseek client error", exc_info=exc)
        return None

    async def _enforce_rate_limit(self) -> None:
        """Ensure searches adhere to the slskd rate limits."""

        now = time.monotonic()
        window_start = now - self.rate_limit_window
        self.search_timestamps = [t for t in self.search_timestamps if t >= window_start]

        if len(self.search_timestamps) >= self.max_searches_per_window:
            wait_time = self.search_timestamps[0] + self.rate_limit_window - now
            if wait_time > 0:
                logger.debug(
                    "Rate limit reached, waiting",
                    extra={"seconds": round(wait_time, 2)},
                )
                await asyncio.sleep(wait_time)

        self.search_timestamps.append(time.monotonic())

    async def search(self, query: str, timeout: int = 30) -> List[TrackResult]:
        """Search for tracks matching the given query via slskd."""

        await self._enforce_rate_limit()
        payload = {
            "searchText": query,
            "timeout": timeout * 1000,
            "filterResponses": True,
        }
        resp = await self._make_request("POST", "searches", json=payload)
        if not resp or "id" not in resp:
            return []
        search_id = resp["id"]

        results: List[TrackResult] = []
        for _ in range(timeout):
            responses = await self._make_request("GET", f"searches/{search_id}/responses")
            if not responses:
                await asyncio.sleep(1)
                continue

            for response in responses:
                username = response.get("username", "")
                free_slots = response.get("freeUploadSlots", 0)
                upload_speed = response.get("uploadSpeed", 0)
                queue_length = response.get("queueLength", 0)

                for file_info in response.get("files", []) or []:
                    filename = file_info.get("filename", "")
                    quality = Path(filename).suffix.lstrip(".") if filename else ""
                    results.append(
                        TrackResult(
                            username=username,
                            filename=filename,
                            size=int(file_info.get("size", 0) or 0),
                            bitrate=file_info.get("bitRate"),
                            duration=file_info.get("length"),
                            quality=quality,
                            free_upload_slots=int(free_slots or 0),
                            upload_speed=int(upload_speed or 0),
                            queue_length=int(queue_length or 0),
                        )
                    )
            break

        return results

    async def download(self, username: str, filename: str, size: int = 0) -> bool:
        """Initiate a download for the specified Soulseek user and file."""

        payload = [
            {
                "filename": filename,
                "size": size,
                "path": str(self.download_path),
            }
        ]
        resp = await self._make_request(
            "POST", f"transfers/downloads/{username}", json=payload
        )
        return resp is not None

