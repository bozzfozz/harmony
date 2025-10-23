from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import SecurityConfig
from app.db import init_db, session_scope
from app.ui.session import UiFeatures, UiSessionManager
from app.ui.session_store import (
    StoredUiSession,
    UiSessionRecord,
    UiSessionStore,
)


@pytest.fixture()
def ui_session_store(tmp_path: Path) -> UiSessionStore:
    _ = tmp_path  # Ensure the sqlite database is isolated per-test.
    init_db()
    return UiSessionStore(session_factory=session_scope)


@pytest.fixture()
def ui_session_manager(ui_session_store: UiSessionStore) -> UiSessionManager:
    security = SecurityConfig(
        profile="test",
        api_keys=("test-api-key",),
        allowlist=(),
        allowed_origins=(),
        _require_auth_default=True,
        _rate_limiting_default=False,
        ui_cookies_secure=False,
    )
    return UiSessionManager(
        security,
        role_default="operator",
        role_overrides={},
        session_ttl=timedelta(minutes=60),
        features=UiFeatures(
            spotify=True,
            soulseek=True,
            dlq=True,
            imports=True,
        ),
        store=ui_session_store,
    )


def test_ui_session_store_persists_and_mutates_rows(
    ui_session_store: UiSessionStore,
) -> None:
    store = ui_session_store
    issued_at = datetime(2024, 1, 2, 15, 30, 0)
    last_seen = datetime(2024, 1, 2, 16, 45, 0)
    identifier = "session-123"

    session = StoredUiSession(
        identifier=identifier,
        role="member",
        fingerprint="fingerprint-abc",
        issued_at=issued_at,
        last_seen_at=last_seen,
        feature_spotify=True,
        feature_soulseek=False,
        feature_dlq=True,
        feature_imports=False,
    )

    store.create_session(session)

    stored = store.get_session(identifier)
    assert stored is not None
    assert stored.identifier == identifier
    assert stored.issued_at == issued_at.replace(tzinfo=UTC)
    assert stored.last_seen_at == last_seen.replace(tzinfo=UTC)
    assert stored.feature_spotify is True
    assert stored.feature_soulseek is False
    assert stored.feature_dlq is True
    assert stored.feature_imports is False
    assert stored.spotify_free_ingest_job_id is None
    assert stored.spotify_backfill_job_id is None

    updated_last_seen = datetime(2024, 1, 3, 9, 0, 0)
    assert store.update_last_seen(identifier, updated_last_seen) is True

    stored = store.get_session(identifier)
    assert stored is not None
    assert stored.last_seen_at == updated_last_seen.replace(tzinfo=UTC)

    assert store.set_spotify_free_ingest_job_id(identifier, "job-free") is True
    assert store.set_spotify_backfill_job_id(identifier, "job-backfill") is True

    stored = store.get_session(identifier)
    assert stored is not None
    assert stored.spotify_free_ingest_job_id == "job-free"
    assert stored.spotify_backfill_job_id == "job-backfill"

    assert store.clear_job_state(identifier) is True

    stored = store.get_session(identifier)
    assert stored is not None
    assert stored.spotify_free_ingest_job_id is None
    assert stored.spotify_backfill_job_id is None

    deleted = store.delete_session(identifier)
    assert deleted is not None
    assert deleted.identifier == identifier
    assert deleted.issued_at == issued_at.replace(tzinfo=UTC)
    assert deleted.last_seen_at == updated_last_seen.replace(tzinfo=UTC)

    assert store.get_session(identifier) is None
    with session_scope() as db_session:
        assert db_session.get(UiSessionRecord, identifier) is None


def test_ui_session_store_returns_false_for_missing_session(
    ui_session_store: UiSessionStore,
) -> None:
    store = ui_session_store
    identifier = "missing-session"
    timestamp = datetime(2024, 1, 4, 12, 0, 0)

    assert store.get_session(identifier) is None
    assert store.update_last_seen(identifier, timestamp) is False
    assert store.set_spotify_free_ingest_job_id(identifier, "job") is False
    assert store.set_spotify_backfill_job_id(identifier, "job") is False
    assert store.clear_job_state(identifier) is False
    assert store.delete_session(identifier) is None


def test_ui_session_manager_updates_session_job_state_immediately(
    ui_session_manager: UiSessionManager,
) -> None:
    manager = ui_session_manager

    async def _exercise() -> None:
        session = await manager.create_session("test-api-key")

        assert session.jobs.spotify_free_ingest_job_id is None
        assert session.jobs.spotify_backfill_job_id is None

        await manager.set_spotify_free_ingest_job_id(
            session.identifier,
            "job-free",
            session=session,
        )
        assert session.jobs.spotify_free_ingest_job_id == "job-free"
        assert await manager.get_spotify_free_ingest_job_id(session.identifier) == "job-free"

        await manager.set_spotify_backfill_job_id(
            session.identifier,
            "job-backfill",
            session=session,
        )
        assert session.jobs.spotify_backfill_job_id == "job-backfill"
        assert await manager.get_spotify_backfill_job_id(session.identifier) == "job-backfill"

        await manager.clear_job_state(session.identifier, session=session)
        assert session.jobs.spotify_free_ingest_job_id is None
        assert session.jobs.spotify_backfill_job_id is None

    asyncio.run(_exercise())
