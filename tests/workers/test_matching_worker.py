from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.matching_engine import MusicMatchingEngine
from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Match, QueueJobStatus
from app.orchestrator.handlers import (
    MatchingHandlerDeps,
    MatchingJobError,
    handle_matching,
)
from app.utils.settings_store import read_setting
from app.workers.persistence import QueueJobDTO


def _make_job(payload: dict, *, job_id: int = 1, attempts: int = 1) -> QueueJobDTO:
    now = datetime.utcnow()
    return QueueJobDTO(
        id=job_id,
        type="matching",
        payload=payload,
        priority=0,
        attempts=attempts,
        available_at=now,
        lease_expires_at=None,
        status=QueueJobStatus.LEASED,
        idempotency_key=None,
        last_error=None,
        result_payload=None,
        lease_timeout_seconds=60,
    )


@pytest.mark.asyncio
async def test_handle_matching_persists_matches() -> None:
    reset_engine_for_tests()
    init_db()
    deps = MatchingHandlerDeps(
        engine=MusicMatchingEngine(),
        session_factory=session_scope,
        confidence_threshold=0.3,
    )

    payload = {
        "type": "spotify-to-soulseek",
        "spotify_track": {
            "id": "track-1",
            "name": "Sample Song",
            "artists": [{"name": "Sample Artist"}],
        },
        "candidates": [
            {"id": "cand-1", "filename": "Sample Song.mp3", "username": "dj", "bitrate": 320},
            {"id": "cand-2", "filename": "Other.mp3", "username": "other", "bitrate": 128},
        ],
    }

    job = _make_job(payload)
    result = await handle_matching(job, deps)

    assert result["stored"] == 1
    assert result["discarded"] == 1
    assert result["matches"][0]["candidate"]["id"] == "cand-1"

    with session_scope() as session:
        matches = session.execute(select(Match)).scalars().all()
        assert len(matches) == 1
        assert matches[0].target_id == "cand-1"

    assert read_setting("metrics.matching.last_discarded") == "1"


@pytest.mark.asyncio
async def test_handle_matching_invalid_payload() -> None:
    reset_engine_for_tests()
    init_db()
    deps = MatchingHandlerDeps(engine=MusicMatchingEngine(), session_factory=session_scope)

    job = _make_job({"type": "spotify-to-soulseek"})
    with pytest.raises(MatchingJobError) as exc:
        await handle_matching(job, deps)

    assert exc.value.code == "invalid_payload"
    assert exc.value.retry is False


@pytest.mark.asyncio
async def test_handle_matching_no_candidates_above_threshold() -> None:
    reset_engine_for_tests()
    init_db()
    deps = MatchingHandlerDeps(
        engine=MusicMatchingEngine(),
        session_factory=session_scope,
        confidence_threshold=0.95,
    )

    payload = {
        "type": "spotify-to-soulseek",
        "spotify_track": {"id": "track-1", "name": "Sample Song", "artists": [{"name": "Sample Artist"}]},
        "candidates": [
            {"id": "cand-1", "filename": "Sample Song.mp3", "username": "dj", "bitrate": 192},
        ],
    }

    job = _make_job(payload)
    with pytest.raises(MatchingJobError) as exc:
        await handle_matching(job, deps)

    assert exc.value.code == "no_match"
    assert exc.value.retry is False
