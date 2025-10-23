from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.db import session_scope
from app.models import ActivityEvent
from app.utils.activity import (
    ActivityEntry,
    ActivityManager,
    record_worker_started,
)
from app.utils.events import WORKER_RESTARTED


class _StubResponseCache:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def invalidate_path(self, path: str, *, reason: str | None = None) -> None:
        self.calls.append((path, reason))


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def test_activity_manager_record_and_list_persist_events_and_invalidate_cache() -> None:
    manager = ActivityManager(max_entries=5, page_cache_limit=3)
    response_cache = _StubResponseCache()
    manager.configure_response_cache(response_cache, paths=("api/activity",))

    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    entry = manager.record(
        action_type="download",
        status="completed",
        timestamp=timestamp,
        details={"path": "/music/example.flac"},
    )

    assert response_cache.calls == [("/api/activity", "activity_updated")]

    with session_scope() as session:
        stored_events = session.query(ActivityEvent).all()
    assert len(stored_events) == 1
    stored_event = stored_events[0]
    assert stored_event.type == "download"
    assert stored_event.status == "completed"
    assert stored_event.details == {"path": "/music/example.flac"}

    items = manager.list()
    assert items == [entry.as_dict()]
    assert items[0]["timestamp"] == _iso(timestamp)


def test_activity_manager_fetch_uses_page_cache_and_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        (datetime(2024, 1, 1, 9, 30, tzinfo=UTC), "oldest"),
        (datetime(2024, 1, 2, 9, 30, tzinfo=UTC), "middle"),
        (datetime(2024, 1, 3, 9, 30, tzinfo=UTC), "newest"),
    ]
    with session_scope() as session:
        for ts, label in events:
            session.add(
                ActivityEvent(
                    timestamp=ts,
                    type="worker",
                    status=label,
                    details={"label": label},
                )
            )

    manager = ActivityManager(max_entries=10, page_cache_limit=2)

    first_page, total = manager.fetch(limit=1, offset=0)
    assert total == 3
    assert first_page[0]["status"] == "newest"

    key_first = manager._cache_key(limit=1, offset=0, type_filter=None, status_filter=None)
    assert key_first in manager._page_cache

    second_page, _ = manager.fetch(limit=1, offset=1)
    assert second_page[0]["status"] == "middle"
    key_second = manager._cache_key(limit=1, offset=1, type_filter=None, status_filter=None)
    assert key_second in manager._page_cache
    assert len(manager._page_cache) == 2

    third_page, _ = manager.fetch(limit=1, offset=2)
    assert third_page[0]["status"] == "oldest"
    key_third = manager._cache_key(limit=1, offset=2, type_filter=None, status_filter=None)
    assert key_third in manager._page_cache
    assert len(manager._page_cache) == 2
    assert key_first not in manager._page_cache

    @contextmanager
    def _fail_session_scope():
        raise AssertionError("fetch should use cached page")
        yield  # pragma: no cover

    monkeypatch.setattr("app.utils.activity.session_scope", _fail_session_scope)

    cached_page, cached_total = manager.fetch(limit=1, offset=2)
    assert cached_page == third_page
    assert cached_total == total


def test_refresh_cache_clears_page_cache_and_invalidates_response_cache() -> None:
    with session_scope() as session:
        session.add_all(
            [
                ActivityEvent(
                    timestamp=datetime(2024, 2, 1, 10, 0, tzinfo=UTC),
                    type="worker",
                    status="started",
                    details={"label": "alpha"},
                ),
                ActivityEvent(
                    timestamp=datetime(2024, 2, 1, 11, 0, tzinfo=UTC),
                    type="worker",
                    status="stopped",
                    details={"label": "beta"},
                ),
            ]
        )

    manager = ActivityManager(max_entries=5, page_cache_limit=2)
    response_cache = _StubResponseCache()
    manager.configure_response_cache(response_cache, paths=("activity",))

    manager.fetch(limit=1, offset=0)
    assert manager._page_cache

    manager.refresh_cache()

    assert not manager._page_cache
    assert response_cache.calls == [("/activity", "activity_updated")]

    listed = manager.list()
    assert [item["status"] for item in listed] == ["stopped", "started"]


def test_extend_inserts_entries_and_clears_page_cache() -> None:
    manager = ActivityManager(max_entries=3, page_cache_limit=2)
    response_cache = _StubResponseCache()
    manager.configure_response_cache(response_cache, paths=("activity",))

    manager.fetch(limit=1, offset=0)
    assert manager._page_cache

    base_time = datetime(2024, 3, 1, 8, 0, tzinfo=UTC)
    entries = [
        ActivityEntry(timestamp=base_time + timedelta(minutes=idx), type="worker", status=f"s{idx}")
        for idx in range(3)
    ]

    manager.extend(entries[:2])

    assert not manager._page_cache
    assert response_cache.calls == [("/activity", "activity_updated")]

    listed = manager.list()
    assert [item["status"] for item in listed] == ["s0", "s1"]

    manager.extend(entries)
    listed = manager.list()
    assert [item["status"] for item in listed] == ["s0", "s1", "s2"]
    assert response_cache.calls == [
        ("/activity", "activity_updated"),
        ("/activity", "activity_updated"),
    ]


def test_record_worker_started_enriches_previous_status(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ActivityManager(max_entries=5, page_cache_limit=4)
    response_cache = _StubResponseCache()
    manager.configure_response_cache(response_cache, paths=("activity",))

    monkeypatch.setattr("app.utils.activity.activity_manager", manager)

    def _fake_read_worker_status(worker: str) -> tuple[str | None, str | None]:
        assert worker == "worker-1"
        return ("2023-12-31T23:59:00Z", "stopped")

    monkeypatch.setattr("app.utils.activity.read_worker_status", _fake_read_worker_status)

    timestamp = datetime(2024, 4, 1, 9, 0, tzinfo=UTC)
    entry = record_worker_started("worker-1", timestamp=timestamp)

    assert entry["status"] == WORKER_RESTARTED
    details = entry["details"]
    assert details["worker"] == "worker-1"
    assert details["previous_status"] == "stopped"
    assert details["timestamp"] == _iso(timestamp)

    with session_scope() as session:
        stored = session.query(ActivityEvent).one()
    assert stored.type == "worker"
    assert stored.status == WORKER_RESTARTED
    assert stored.details["worker"] == "worker-1"
    assert stored.details["previous_status"] == "stopped"
    assert response_cache.calls == [("/activity", "activity_updated")]
