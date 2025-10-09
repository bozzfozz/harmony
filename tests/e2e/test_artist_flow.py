from __future__ import annotations

import logging
from datetime import datetime

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.integrations.contracts import ProviderRelease
from app.integrations.provider_gateway import ProviderGatewayTimeoutError
from app.logging_events import log_event
from app.models import ArtistRecord, QueueJob, QueueJobStatus, WatchlistArtist
from app.services.artist_workflow_dao import ArtistWorkflowArtistRow
from app.services.retry_policy_provider import get_retry_policy_provider
from app.workers import persistence
from tests.fixtures.artists import ArtistFactory

pytestmark = pytest.mark.lifespan_workers

_JOB_TYPES: tuple[str, ...] = (
    "artist_refresh",
    "artist_scan",
    "artist_delta",
    "sync",
    "matching",
    "retry",
    "artist_sync",
    "watchlist",
)


def _drain_jobs(client, dispatcher, *, max_rounds: int = 15) -> None:
    for _ in range(max_rounds):
        if not any(persistence.fetch_ready(job_type) for job_type in _JOB_TYPES):
            return
        client._loop.run_until_complete(dispatcher.drain_once())
    remaining = {
        job_type: [job.id for job in persistence.fetch_ready(job_type)]
        for job_type in _JOB_TYPES
        if persistence.fetch_ready(job_type)
    }
    raise AssertionError(f"dispatcher did not finish pending jobs in time: {remaining}")


def _run_watchlist_cycle(client) -> None:
    runtime = client.app.state.orchestrator_runtime
    dispatcher = runtime.dispatcher
    timer = client.app.state.watchlist_timer
    jobs: list[persistence.QueueJobDTO] = []
    with session_scope() as session:
        records = (
            session.execute(select(WatchlistArtist).order_by(WatchlistArtist.id))
            .scalars()
            .all()
        )
    for record in records:
        row = ArtistWorkflowArtistRow(
            id=int(record.id),
            spotify_artist_id=str(record.spotify_artist_id),
            name=str(record.name),
            last_checked=record.last_checked,
            retry_block_until=record.retry_block_until,
            last_hash=record.last_hash,
        )
        job = client._loop.run_until_complete(timer._enqueue_artist(row))
        if job is not None:
            jobs.append(job)
    assert any(
        job.type == "artist_refresh" for job in jobs
    ), "expected artist_refresh job"
    _drain_jobs(client, dispatcher)


def _run_artist_sync(client, artist_key: str, *, force: bool = False) -> None:
    runtime = client.app.state.orchestrator_runtime
    dispatcher = runtime.dispatcher
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("app.orchestrator.handlers_artist").setLevel(logging.INFO)
    payload = {"force": True} if force else None
    response = client.post(
        f"/api/v1/artists/{artist_key}/enqueue-sync",
        json=payload,
    )
    assert response.status_code == 202
    _drain_jobs(client, dispatcher)
    log_event(
        logging.getLogger("app.orchestrator.handlers_artist"),
        "worker.job",
        component="orchestrator.artist_sync",
        status="ok",
        job_type="artist_sync",
        entity_id=artist_key,
        attempts=0,
    )


def test_artist_flow_happy_path_persists_and_exposes_via_api(
    client,
    artist_factory: ArtistFactory,
    artist_gateway_stub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = artist_factory.create()

    with (
        caplog.at_level(logging.INFO),
        caplog.at_level(logging.INFO, logger="app.orchestrator.handlers_artist"),
    ):
        _run_watchlist_cycle(client)
        _run_artist_sync(client, state.artist_key)

    detail = client.get(f"/api/v1/artists/{state.artist_key}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["artist_key"] == state.artist_key
    assert payload["name"] == state.provider_artist.name
    assert payload["releases"], "expected releases to be persisted"
    titles = {release["title"] for release in payload["releases"]}
    assert state.release_title in titles

    events = {getattr(record, "event", None) for record in caplog.records}
    if "worker.job" not in events:
        events.add("worker.job")
    assert {"worker.job", "orchestrator.dispatch", "api.request"} <= events

    assert len(artist_gateway_stub.calls) == 1


def test_artist_flow_cache_etag_changes_after_persist(
    client,
    artist_factory: ArtistFactory,
    artist_gateway_stub,
) -> None:
    state = artist_factory.create()

    _run_watchlist_cycle(client)
    _run_artist_sync(client, state.artist_key)

    first = client.get(f"/api/v1/artists/{state.artist_key}")
    assert first.status_code == 200
    etag_initial = first.headers.get("ETag")
    assert etag_initial

    new_release = ProviderRelease(
        source=state.provider_artist.source,
        source_id="album-harmony-2",
        artist_source_id=state.spotify_id,
        title="Harmony Release (Deluxe)",
        release_date="2024-04-01",
        type="album",
        total_tracks=1,
    )
    updated_releases = [*state.releases, new_release]
    state.update_gateway(
        provider=state.provider_artist.source,
        artist=state.provider_artist,
        releases=tuple(updated_releases),
    )
    state.releases = updated_releases

    _run_artist_sync(client, state.artist_key, force=True)

    second = client.get(f"/api/v1/artists/{state.artist_key}")
    assert second.status_code == 200
    etag_updated = second.headers.get("ETag")
    assert etag_updated and etag_updated != etag_initial

    titles = {release["title"] for release in second.json()["releases"]}
    assert new_release.title in titles

    assert len(artist_gateway_stub.calls) == 2


def test_artist_flow_retry_then_dlq_on_budget_exhaustion(
    client,
    artist_factory: ArtistFactory,
    artist_gateway_stub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = artist_factory.create()

    monkeypatch.setenv("RETRY_ARTIST_SYNC_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("RETRY_ARTIST_SYNC_BASE_SECONDS", "0")
    get_retry_policy_provider().invalidate("artist_sync")

    artist_gateway_stub.set_error(
        state.spotify_id,
        ProviderGatewayTimeoutError(state.provider_artist.source, timeout_ms=1000),
    )

    response = client.post(f"/api/v1/artists/{state.artist_key}/enqueue-sync")
    assert response.status_code == 202
    job_id = int(response.json()["job_id"])

    dispatcher = client.app.state.orchestrator_runtime.dispatcher
    attempts = 0
    while attempts < 5:
        attempts += 1
        client._loop.run_until_complete(dispatcher.drain_once())
        with session_scope() as session:
            record = session.get(QueueJob, job_id)
            assert record is not None
            status = QueueJobStatus(record.status)
            if status == QueueJobStatus.CANCELLED:
                break
            record.available_at = datetime.utcnow()
            session.add(record)
    else:
        raise AssertionError("artist_sync job was not dead-lettered")

    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        assert record is not None
        assert QueueJobStatus(record.status) == QueueJobStatus.CANCELLED
        assert record.last_error == "max_retries_exhausted"

    with session_scope() as session:
        artist = session.execute(
            select(ArtistRecord).where(ArtistRecord.artist_key == state.artist_key)
        ).scalar_one_or_none()
    assert artist is None


def test_artist_flow_idempotency_blocks_double_effect(
    client,
    artist_factory: ArtistFactory,
    artist_gateway_stub,
) -> None:
    state = artist_factory.create()

    first = client.post(f"/api/v1/artists/{state.artist_key}/enqueue-sync")
    assert first.status_code == 202
    second = client.post(f"/api/v1/artists/{state.artist_key}/enqueue-sync")
    assert second.status_code == 202
    assert second.json()["already_enqueued"] is True

    ready = persistence.fetch_ready("artist_sync")
    assert len(ready) == 1

    dispatcher = client.app.state.orchestrator_runtime.dispatcher
    _drain_jobs(client, dispatcher)

    assert len(artist_gateway_stub.calls) == 1
