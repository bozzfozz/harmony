from datetime import datetime, timedelta

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.main import MetricsRegistry, _METRIC_BUCKETS
from app.models import Download
from app.services.dlq_service import DLQService


@pytest.fixture(autouse=True)
def setup_database() -> None:
    reset_engine_for_tests()
    init_db()


@pytest.fixture
def service() -> DLQService:
    registry = MetricsRegistry(_METRIC_BUCKETS)
    return DLQService(metrics_registry=registry)


class StubWorker:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    async def enqueue(self, payload: dict) -> None:
        self.jobs.append(payload)


def _seed_download(**overrides: object) -> int:
    params = {
        "filename": "stalled.flac",
        "state": "dead_letter",
        "progress": 0.0,
        "priority": 3,
        "username": "tester",
        "retry_count": 2,
        "last_error": "network timeout",
        "created_at": datetime.utcnow() - timedelta(hours=2),
        "updated_at": datetime.utcnow() - timedelta(hours=1),
        "request_payload": {
            "file": {"filename": "stalled.flac", "priority": 3},
            "username": "tester",
            "priority": 3,
        },
    }
    params.update(overrides)
    with session_scope() as session:
        record = Download(**params)
        session.add(record)
        session.flush()
        download_id = record.id
    return int(download_id)


def test_list_entries_supports_filters(service: DLQService) -> None:
    first_id = _seed_download(
        created_at=datetime.utcnow() - timedelta(days=2), last_error="network timeout"
    )
    _seed_download(created_at=datetime.utcnow() - timedelta(hours=1), last_error="auth failure")
    _seed_download(state="queued", last_error="should not appear")

    with session_scope() as session:
        result = service.list_entries(
            session,
            page=1,
            page_size=10,
            order_by="created_at",
            order_dir="desc",
            reason="network",
            created_from=datetime.utcnow() - timedelta(days=3),
            created_to=datetime.utcnow(),
        )

    assert result.total == 1
    assert result.items[0].id == str(first_id)
    assert result.items[0].reason == "network"


@pytest.mark.asyncio
async def test_requeue_bulk_is_idempotent(service: DLQService) -> None:
    download_id = _seed_download()
    worker = StubWorker()

    with session_scope() as session:
        result = await service.requeue_bulk(
            session, ids=[download_id], worker=worker, actor="tester"
        )

    assert result.requeued == [str(download_id)]
    assert not result.skipped
    assert worker.jobs[0]["files"][0]["download_id"] == download_id

    with session_scope() as session:
        repeat = await service.requeue_bulk(
            session, ids=[download_id], worker=worker, actor="tester"
        )

    assert repeat.requeued == []
    assert repeat.skipped[0]["reason"] == "already_queued"


@pytest.mark.asyncio
async def test_requeue_skips_missing_payload(service: DLQService) -> None:
    download_id = _seed_download(request_payload=None)
    worker = StubWorker()

    with session_scope() as session:
        result = await service.requeue_bulk(
            session, ids=[download_id], worker=worker, actor="tester"
        )

    assert result.requeued == []
    assert result.skipped[0]["reason"] == "missing_payload"


def test_purge_by_older_than_and_reason(service: DLQService) -> None:
    old_id = _seed_download(
        created_at=datetime.utcnow() - timedelta(days=5), last_error="network timeout"
    )
    _seed_download(created_at=datetime.utcnow() - timedelta(hours=12), last_error="auth failure")

    with session_scope() as session:
        result = service.purge_bulk(
            session,
            ids=None,
            older_than=datetime.utcnow() - timedelta(days=2),
            reason="network",
            actor="tester",
        )

    assert result.purged == 1
    with session_scope() as session:
        assert session.get(Download, old_id) is None


def test_stats_returns_expected_counts(service: DLQService) -> None:
    _seed_download(last_error="network timeout")
    _seed_download(last_error="network unreachable")
    _seed_download(last_error="auth failure", created_at=datetime.utcnow() - timedelta(hours=23))

    with session_scope() as session:
        stats = service.stats(session)

    assert stats.total == 3
    assert stats.by_reason["network"] == 2
    assert stats.last_24h >= 1
