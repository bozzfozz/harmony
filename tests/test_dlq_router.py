from datetime import datetime, timedelta
from typing import Any, Dict

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.main import app
from app.models import Download
from tests.simple_client import SimpleTestClient


@pytest.fixture(autouse=True)
def setup_database() -> None:
    reset_engine_for_tests()
    init_db()


class StubWorker:
    def __init__(self) -> None:
        self.enqueued: list[Dict[str, Any]] = []

    async def enqueue(self, payload: Dict[str, Any]) -> None:
        self.enqueued.append(payload)


def _seed_dlq_entry(**overrides: Any) -> int:
    payload = {
        "filename": "stalled.flac",
        "state": "dead_letter",
        "progress": 0.0,
        "priority": 2,
        "username": "tester",
        "retry_count": 1,
        "last_error": overrides.get("last_error", "network timeout"),
        "created_at": overrides.get("created_at", datetime.utcnow() - timedelta(hours=3)),
        "updated_at": overrides.get("updated_at", datetime.utcnow() - timedelta(hours=2)),
        "request_payload": overrides.get(
            "request_payload",
            {
                "file": {"filename": "stalled.flac", "priority": 2},
                "username": "tester",
                "priority": 2,
            },
        ),
    }
    with session_scope() as session:
        record = Download(**payload)
        session.add(record)
        session.flush()
        return int(record.id)


@pytest.fixture
def client() -> SimpleTestClient:
    with SimpleTestClient(app) as instance:
        yield instance


def test_list_endpoint_returns_items(client: SimpleTestClient) -> None:
    first_id = _seed_dlq_entry(
        created_at=datetime.utcnow() - timedelta(days=1), last_error="network timeout"
    )
    _seed_dlq_entry(last_error="auth failure")

    response = client.get("/api/v1/dlq", params={"order_by": "created_at", "order_dir": "asc"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["total"] == 2
    first_item = payload["data"]["items"][0]
    assert first_item["id"] == str(first_id)
    assert first_item["reason"] == "network"


def test_requeue_endpoint_requeues_entries(client: SimpleTestClient) -> None:
    entry_id = _seed_dlq_entry()
    worker = StubWorker()
    app.state.sync_worker = worker

    response = client.post("/api/v1/dlq/requeue", json={"ids": [str(entry_id)]})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["requeued"] == [str(entry_id)]
    assert worker.enqueued[0]["files"][0]["download_id"] == entry_id

    # second attempt should skip as already queued
    response_repeat = client.post("/api/v1/dlq/requeue", json={"ids": [str(entry_id)]})
    assert response_repeat.status_code == 200
    repeat_body = response_repeat.json()
    assert repeat_body["data"]["skipped"][0]["reason"] == "already_queued"


def test_requeue_returns_not_found_for_unknown_id(client: SimpleTestClient) -> None:
    app.state.sync_worker = StubWorker()
    response = client.post("/api/v1/dlq/requeue", json={"ids": ["999"]})
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "NOT_FOUND"


def test_purge_endpoint_supports_ids(client: SimpleTestClient) -> None:
    entry_id = _seed_dlq_entry()
    response = client.post("/api/v1/dlq/purge", json={"ids": [str(entry_id)]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["purged"] == 1


def test_purge_validates_payload(client: SimpleTestClient) -> None:
    response = client.post("/api/v1/dlq/purge", json={"reason": "network"})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def test_stats_endpoint_returns_counts(client: SimpleTestClient) -> None:
    _seed_dlq_entry(last_error="network timeout")
    _seed_dlq_entry(last_error="auth failure", created_at=datetime.utcnow() - timedelta(hours=1))

    response = client.get("/api/v1/dlq/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["total"] == 2
    assert payload["data"]["by_reason"]["network"] == 1
