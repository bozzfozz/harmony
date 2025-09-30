"""Utilities coordinating Spotify-specific background work."""

from __future__ import annotations

from typing import Optional, Sequence

from app.services.backfill_service import BackfillJobStatus
from app.services.free_ingest_service import IngestSubmission, JobStatus
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


async def enqueue_spotify_free_import(
    service: SpotifyDomainService,
    *,
    playlist_links: Sequence[str] | None,
    tracks: Sequence[str] | None,
    batch_hint: int | None,
) -> IngestSubmission:
    """Schedule a Spotify FREE import job via the domain service."""

    return await service._submit_free_import(  # pragma: no cover - exercised via service tests
        playlist_links=playlist_links,
        tracks=tracks,
        batch_hint=batch_hint,
    )


def get_spotify_free_import_job(
    service: SpotifyDomainService, job_id: str
) -> Optional[JobStatus]:
    """Fetch the current state for a Spotify FREE import job."""

    return service.get_free_ingest_job(job_id)


__all__ = [
    "enqueue_spotify_backfill",
    "get_spotify_backfill_status",
    "enqueue_spotify_free_import",
    "get_spotify_free_import_job",
]
