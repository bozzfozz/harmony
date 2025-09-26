"""Stub worker for future Spotify FREE import processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class ImportJob:
    """Represents a queued playlist import job."""

    session_id: str
    playlist_id: str


class ImportWorker:
    """Placeholder implementation until playlist ingestion is implemented."""

    async def start(self) -> None:  # pragma: no cover - placeholder
        return None

    async def stop(self) -> None:  # pragma: no cover - placeholder
        return None

    async def enqueue(self, jobs: Iterable[ImportJob]) -> None:  # pragma: no cover - placeholder
        _ = list(jobs)
        return None
