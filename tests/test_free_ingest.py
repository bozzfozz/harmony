from __future__ import annotations

import pytest

from app.db import session_scope
from app.dependencies import get_app_config
from app.models import IngestItem, IngestItemState, IngestJob, IngestJobState
from app.services.free_ingest_service import FreeIngestService


class _DummySoulseekClient:
    """Minimal soulseek client stub for unit tests."""

    async def search(self, *args, **kwargs):  # pragma: no cover - defensive stub
        raise RuntimeError("search should not be called in tests")


@pytest.fixture
def free_ingest_service() -> FreeIngestService:
    config = get_app_config()
    return FreeIngestService(
        config=config,
        soulseek_client=_DummySoulseekClient(),
        sync_worker=None,
    )


def _create_job(
    job_id: str,
    *,
    skipped_tracks: int = 0,
    skipped_playlists: int = 0,
    error: str | None = None,
) -> None:
    with session_scope() as session:
        job = IngestJob(
            id=job_id,
            source="FREE",
            state=IngestJobState.NORMALIZED.value,
            skipped_playlists=skipped_playlists,
            skipped_tracks=skipped_tracks,
            error=error,
        )
        session.add(job)


def _add_items(job_id: str, state: IngestItemState, count: int) -> None:
    if count <= 0:
        return
    with session_scope() as session:
        for index in range(count):
            item = IngestItem(
                job_id=job_id,
                source_type="FILE",
                playlist_url=None,
                raw_line=None,
                artist=None,
                title=None,
                album=None,
                duration_sec=None,
                dedupe_hash=f"{job_id}_{state.value}_{index}",
                source_fingerprint=f"fp_{job_id}_{state.value}_{index}",
                state=state.value,
                error=None,
            )
            session.add(item)


@pytest.mark.anyio("asyncio")
async def test_partial_and_skip_preserves_partial_error(
    free_ingest_service: FreeIngestService,
) -> None:
    job_id = "job_partial_skip"
    _create_job(job_id, skipped_tracks=5, error="limit")
    _add_items(job_id, IngestItemState.QUEUED, 3)
    _add_items(job_id, IngestItemState.FAILED, 2)

    await free_ingest_service._finalise_job_state(
        job_id,
        total_tracks=5,
        queued_tracks=3,
        failed_tracks=2,
        skipped_tracks=5,
        skip_reason="limit",
        error="limit",
    )

    status = free_ingest_service.get_job_status(job_id)
    assert status is not None
    assert status.state == IngestJobState.COMPLETED.value
    assert status.error == "partial queued=3 failed=2"
    assert status.skip_reason == "limit"
    assert status.queued_tracks == 3
    assert status.failed_tracks == 2
    assert status.skipped_tracks == 5

    with session_scope() as session:
        job = session.get(IngestJob, job_id)
        assert job is not None
        assert job.error == "partial queued=3 failed=2||skip_reason=limit"


@pytest.mark.anyio("asyncio")
async def test_only_skip_sets_error_to_reason_without_partial(
    free_ingest_service: FreeIngestService,
) -> None:
    job_id = "job_only_skip"
    _create_job(job_id, skipped_tracks=10, error="duplicate")

    await free_ingest_service._finalise_job_state(
        job_id,
        total_tracks=0,
        queued_tracks=0,
        failed_tracks=0,
        skipped_tracks=10,
        skip_reason="duplicate",
        error="duplicate",
    )

    status = free_ingest_service.get_job_status(job_id)
    assert status is not None
    assert status.state == IngestJobState.COMPLETED.value
    assert status.error == "duplicate"
    assert status.skip_reason == "duplicate"
    assert status.failed_tracks == 0
    assert status.queued_tracks == 0
    assert status.skipped_tracks == 10

    with session_scope() as session:
        job = session.get(IngestJob, job_id)
        assert job is not None
        assert job.error == "duplicate"


@pytest.mark.anyio("asyncio")
async def test_only_fail_sets_state_failed(
    free_ingest_service: FreeIngestService,
) -> None:
    job_id = "job_only_fail"
    _create_job(job_id, skipped_tracks=0, error=None)
    _add_items(job_id, IngestItemState.FAILED, 5)

    await free_ingest_service._finalise_job_state(
        job_id,
        total_tracks=5,
        queued_tracks=0,
        failed_tracks=5,
        skipped_tracks=0,
        skip_reason=None,
        error=None,
    )

    status = free_ingest_service.get_job_status(job_id)
    assert status is not None
    assert status.state == IngestJobState.FAILED.value
    assert status.error == "failed=5"
    assert status.skip_reason is None
    assert status.failed_tracks == 5
    assert status.queued_tracks == 0
    assert status.skipped_tracks == 0

    with session_scope() as session:
        job = session.get(IngestJob, job_id)
        assert job is not None
        assert job.error == "failed=5"
