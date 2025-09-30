"""Utilities coordinating Spotify-specific background work."""

from __future__ import annotations

from typing import Optional

from app.services.backfill_service import BackfillJobStatus
from app.services.spotify_domain_service import SpotifyDomainService


async def enqueue_spotify_backfill(
    service: SpotifyDomainService,
    *,
    max_items: int | None,
    expand_playlists: bool,
) -> str:
    """Schedule a Spotify backfill job and return its identifier."""

    job = service.create_backfill_job(
        max_items=max_items,
        expand_playlists=expand_playlists,
    )
    await service.enqueue_backfill(job)
    return job.id


def get_spotify_backfill_status(
    service: SpotifyDomainService, job_id: str
) -> Optional[BackfillJobStatus]:
    """Return the current status for the given Spotify backfill job."""

    return service.get_backfill_status(job_id)


__all__ = [
    "enqueue_spotify_backfill",
    "get_spotify_backfill_status",
]
