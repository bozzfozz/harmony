"""Wrapper around the slskd transfers endpoints."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from app.core.soulseek_client import SoulseekClient, SoulseekClientError


class TransfersApiError(RuntimeError):
    """Raised when the slskd transfers API cannot fulfil a request."""


class TransfersApi:
    """Provide a small abstraction for download transfer operations."""

    def __init__(self, client: SoulseekClient) -> None:
        self._client = client

    async def cancel_download(self, download_id: int | str) -> Dict[str, Any]:
        """Cancel a download via slskd."""

        try:
            return await self._client.cancel_download(str(download_id))
        except SoulseekClientError as exc:  # pragma: no cover - network failure path
            raise TransfersApiError(str(exc)) from exc

    async def enqueue(self, *, username: str, files: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Enqueue a new download job for the given user and files."""

        try:
            file_list = list(files)
            return await self._client.enqueue(username, file_list)
        except SoulseekClientError as exc:  # pragma: no cover - network failure path
            raise TransfersApiError(str(exc)) from exc
