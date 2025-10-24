"""Integration tests for :mod:`app.services.watchlist_service`."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.db import init_db, session_scope
from app.errors import AppError, ErrorCode, NotFoundError
from app.models import WatchlistArtist
from app.services.watchlist_service import WatchlistEntry, WatchlistService


@pytest.fixture()
def watchlist_service() -> Iterator[WatchlistService]:
    """Provide a watchlist service bound to a temporary SQLite database."""

    init_db()
    # Touch the database through ``session_scope`` to ensure the SQLite file exists.
    with session_scope():
        pass

    service = WatchlistService()
    service.reset()
    try:
        yield service
    finally:
        service.reset()


@pytest.fixture()
def log_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Capture structured log events emitted via :func:`log_event`."""

    events: list[tuple[str, dict[str, Any]]] = []

    def _capture(_logger: Any, event: str, /, **fields: Any) -> None:
        events.append((event, dict(fields)))

    monkeypatch.setattr("app.services.watchlist_service.log_event", _capture)
    return events


def test_create_entry_detects_duplicates_and_logs_error(
    watchlist_service: WatchlistService, log_events: list[tuple[str, dict[str, Any]]]
) -> None:
    first = watchlist_service.create_entry(artist_key="spotify:artist-1", priority=2)
    assert first.artist_key == "spotify:artist-1"

    with pytest.raises(AppError) as excinfo:
        watchlist_service.create_entry(artist_key="spotify:artist-1", priority=5)

    error = excinfo.value
    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.http_status == 409
    assert error.meta == {"artist_key": "spotify:artist-1"}

    # Duplicate attempts are logged as service errors with structured metadata.
    assert log_events[-1] == (
        "service.call",
        {
            "component": "service.watchlist",
            "operation": "create",
            "status": "error",
            "entity_id": "spotify:artist-1",
            "error": "artist_exists",
        },
    )

    with session_scope() as session:
        total = session.query(WatchlistArtist).count()
    assert total == 1


def test_create_entry_rejects_invalid_artist_keys(
    watchlist_service: WatchlistService, log_events: list[tuple[str, dict[str, Any]]]
) -> None:
    with pytest.raises(AppError) as excinfo:
        watchlist_service.create_entry(artist_key="spotify", priority=0)

    error = excinfo.value
    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.http_status == 422
    assert "provider and identifier" in error.message

    # Invalid input is rejected before any structured log is emitted.
    assert log_events == []
    assert watchlist_service.list_entries() == []


def _list_priorities(service: WatchlistService) -> list[tuple[str, int]]:
    entries = service.list_entries()
    return [(entry.artist_key, entry.priority) for entry in entries]


def test_update_priority_reorders_entries(
    watchlist_service: WatchlistService, log_events: list[tuple[str, dict[str, Any]]]
) -> None:
    low = watchlist_service.create_entry(artist_key="spotify:slow", priority=1)
    high = watchlist_service.create_entry(artist_key="spotify:fast", priority=4)

    del log_events[:]

    updated = watchlist_service.update_priority(artist_key=low.artist_key, priority=10)

    assert isinstance(updated, WatchlistEntry)
    assert updated.artist_key == low.artist_key
    assert updated.priority == 10
    assert _list_priorities(watchlist_service) == [
        (low.artist_key, 10),
        (high.artist_key, high.priority),
    ]

    assert log_events == [
        (
            "service.call",
            {
                "component": "service.watchlist",
                "operation": "update_priority",
                "status": "ok",
                "entity_id": low.artist_key,
                "priority": 10,
            },
        )
    ]


def test_pause_and_resume_entry_persist_state(
    watchlist_service: WatchlistService, log_events: list[tuple[str, dict[str, Any]]]
) -> None:
    entry = watchlist_service.create_entry(artist_key="spotify:paused", priority=3)
    resume_at = datetime(2030, 5, 17, 15, 45, tzinfo=UTC)

    del log_events[:]

    paused = watchlist_service.pause_entry(
        artist_key=entry.artist_key,
        reason="maintenance",
        resume_at=resume_at,
    )

    assert paused.paused is True
    assert paused.pause_reason == "maintenance"
    assert paused.resume_at == resume_at

    expected_resume = resume_at.isoformat().replace("+00:00", "Z")
    assert log_events[0] == (
        "service.call",
        {
            "component": "service.watchlist",
            "operation": "pause",
            "status": "ok",
            "entity_id": entry.artist_key,
            "reason": "maintenance",
            "resume_at": expected_resume,
        },
    )

    resumed = watchlist_service.resume_entry(artist_key=entry.artist_key)
    assert resumed.paused is False
    assert resumed.pause_reason is None
    assert resumed.resume_at is None

    assert log_events[1] == (
        "service.call",
        {
            "component": "service.watchlist",
            "operation": "resume",
            "status": "ok",
            "entity_id": entry.artist_key,
        },
    )


def test_pause_entry_normalises_non_utc_resume(
    watchlist_service: WatchlistService, log_events: list[tuple[str, dict[str, Any]]]
) -> None:
    entry = watchlist_service.create_entry(artist_key="spotify:offset", priority=1)
    resume_local = datetime.fromisoformat("2031-08-12T08:15:00-05:00")

    del log_events[:]

    paused = watchlist_service.pause_entry(
        artist_key=entry.artist_key,
        resume_at=resume_local,
    )

    expected_utc = resume_local.astimezone(UTC)
    assert paused.resume_at == expected_utc

    assert log_events[0] == (
        "service.call",
        {
            "component": "service.watchlist",
            "operation": "pause",
            "status": "ok",
            "entity_id": entry.artist_key,
            "resume_at": expected_utc.isoformat().replace("+00:00", "Z"),
        },
    )


def test_remove_entry_missing_raises_not_found(
    watchlist_service: WatchlistService, log_events: list[tuple[str, dict[str, Any]]]
) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        watchlist_service.remove_entry(artist_key="spotify:unknown")

    error = excinfo.value
    assert error.code is ErrorCode.NOT_FOUND
    assert error.message == "Watchlist entry not found."

    # Not found operations do not emit structured logs.
    assert log_events == []
