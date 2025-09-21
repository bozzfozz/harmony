import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from app.config.settings import config_manager
from app.utils.logging_config import get_logger


logger = get_logger("soulseek_client")


@dataclass
class TrackResult:
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


class SoulseekClient:
    """Async client for slskd (Soulseek daemon)."""

    def __init__(self):
        self.base_url: Optional[str] = None
        self.api_key: Optional[str] = None
        self.download_path: Path = Path("./downloads")
        self._setup_client()

    def _setup_client(self):
        """Initialise client from configuration."""
        config = config_manager.get_soulseek_config()
        self.base_url = config.get("slskd_url", "").rstrip("/")
        self.api_key = config.get("api_key", "")
        download_path_str = config.get("download_path", "./downloads")
        self.download_path = Path(download_path_str)
        self.download_path.mkdir(parents=True, exist_ok=True)
        logger.info("Soulseek client configured: %s", self.base_url)

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def _make_request(self, method: str, endpoint: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            logger.error("Soulseek client not configured")
            return None

        url = f"{self.base_url}/api/v0/{endpoint}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.request(method, url, headers=self._get_headers(), **kwargs) as response:
                    if response.status in [200, 201]:
                        return await response.json()
                    text = await response.text()
                    logger.error("API %s %s failed: %s %s", method, url, response.status, text)
            except Exception as exc:
                logger.error("Request error: %s", exc)
        return None

    async def search(self, query: str, timeout: int = 30) -> List[TrackResult]:
        """Search tracks by query."""

        payload = {"searchText": query, "timeout": timeout * 1000, "filterResponses": True}
        resp = await self._make_request("POST", "searches", json=payload)
        if not resp or "id" not in resp:
            return []
        search_id = resp["id"]

        results: List[TrackResult] = []
        for _ in range(timeout):
            responses = await self._make_request("GET", f"searches/{search_id}/responses")
            if responses:
                for response in responses:
                    for file_info in response.get("files", []) or []:
                        filename = file_info.get("filename", "")
                        quality = Path(filename).suffix.lstrip(".") if filename else ""
                        results.append(
                            TrackResult(
                                username=response.get("username", ""),
                                filename=filename,
                                size=int(file_info.get("size", 0) or 0),
                                bitrate=file_info.get("bitRate"),
                                duration=file_info.get("length"),
                                quality=quality,
                                free_upload_slots=int(response.get("freeUploadSlots", 0) or 0),
                                upload_speed=int(response.get("uploadSpeed", 0) or 0),
                                queue_length=int(response.get("queueLength", 0) or 0),
                            )
                        )
                break
            await asyncio.sleep(1)
        return results

    async def download(self, username: str, filename: str, size: int = 0) -> bool:
        """Initiate a download for the specified Soulseek user and file."""

        payload = [{"filename": filename, "size": size, "path": str(self.download_path)}]
        resp = await self._make_request("POST", f"transfers/downloads/{username}", json=payload)
        return resp is not None

