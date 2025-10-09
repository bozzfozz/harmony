from datetime import datetime, timedelta
from typing import Callable, Sequence

import pytest

from app import dependencies as deps
import app.api.admin_artists as admin_api
from app.api.admin_artists import (
    AdminContext,
    _unregister_admin_routes,
    maybe_register_admin_routes,
)
from app.config import settings as app_settings
from app.db import init_db, reset_engine_for_tests, session_scope
from app.integrations.artist_gateway import ArtistGatewayResponse, ArtistGatewayResult
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.main import app
from app.models import ArtistRecord, ArtistReleaseRecord, QueueJob, QueueJobStatus
from app.orchestrator.handlers_artist import ArtistSyncHandlerDeps
from app.services.artist_dao import ArtistDao, ArtistReleaseUpsertDTO, ArtistUpsertDTO
from app.services.cache import CacheEntry, ResponseCache, build_cache_key
from tests.simple_client import SimpleTestClient
from tests.support.postgres import postgres_schema

pytestmark = pytest.mark.postgres


class StubGateway:
    def __init__(self, response: ArtistGatewayResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, Sequence[str], int]] = []

    async def fetch_artist(
        self, artist_id: str, *, providers: Sequence[str], limit: int
    ) -> ArtistGatewayResponse:
        self.calls.append((artist_id, tuple(providers), limit))
        return self.response


def _make_gateway_response(
    releases: Sequence[ProviderRelease], *, provider: str = "spotify", artist_id: str = "alpha"
) -> ArtistGatewayResponse:
    artist = ProviderArtist(source=provider, name="Alpha", source_id=artist_id)
    result = ArtistGatewayResult(provider=provider, artist=artist, releases=tuple(releases))
    return ArtistGatewayResponse(artist_id=artist_id, results=(result,))


@pytest.fixture(autouse=True)
def configure_admin_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {
        "HARMONY_DISABLE_WORKERS": "1",
        "FEATURE_REQUIRE_AUTH": "0",
        "FEATURE_ADMIN_API": "1",
        "ARTIST_STALENESS_MAX_MIN": "30",
        "ARTIST_RETRY_BUDGET_MAX": "3",
    }

    original_config = deps.get_app_config()
    original_openapi_schema = getattr(app, "openapi_schema", None)
    original_response_cache = getattr(app.state, "response_cache", None)
    original_cache_write_through = getattr(app.state, "cache_write_through", None)
    original_cache_log_evictions = getattr(app.state, "cache_log_evictions", None)
    original_openapi_config = getattr(app.state, "openapi_config", None)
    original_admin_registered = bool(getattr(app.state, "admin_artists_registered", False))

    for key, value in overrides.items():
        monkeypatch.setenv(key, value)

    with postgres_schema("admin", monkeypatch=monkeypatch):
        reset_engine_for_tests()
        init_db()

        deps.get_app_config.cache_clear()
        config = deps.get_app_config()
        maybe_register_admin_routes(app, config=config)
        app.state.response_cache = None
        app.state.cache_write_through = None
        app.state.cache_log_evictions = None
        app.state.openapi_config = config
        app.openapi_schema = None

        try:
            yield
        finally:
            reset_engine_for_tests()

    deps.get_app_config.cache_clear()
    app.state.response_cache = original_response_cache
    app.state.cache_write_through = original_cache_write_through
    app.state.cache_log_evictions = original_cache_log_evictions
    app.state.openapi_config = original_openapi_config
    _unregister_admin_routes(app)
    if original_admin_registered:
        maybe_register_admin_routes(app, config=original_config)
    app.openapi_schema = original_openapi_schema


@pytest.fixture
def install_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]]:
    def _installer(
        gateway: StubGateway, cache: ResponseCache | None = None
    ) -> tuple[AdminContext, ArtistDao]:
        config = deps.get_app_config()
        dao = ArtistDao()
        deps_instance = ArtistSyncHandlerDeps(gateway=gateway, dao=dao, response_cache=cache)
        context = AdminContext(config=config, deps=deps_instance, cache=cache)

        def _override(_ctx=context):  # type: ignore[no-untyped-def]
            return _ctx

        monkeypatch.setitem(app.dependency_overrides, admin_api._build_context, _override)
        return context, dao

    return _installer


def _make_release(source_id: str = "rel-1", title: str = "First") -> ProviderRelease:
    return ProviderRelease(
        source="spotify",
        source_id=source_id,
        artist_source_id="alpha",
        title=title,
        release_date="2024-01-01",
        type="album",
        total_tracks=10,
        version="v1",
        metadata={},
    )


def test_admin_dry_run_shows_delta_no_side_effects(
    install_context: Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]],
) -> None:
    response = _make_gateway_response([_make_release()])
    gateway = StubGateway(response)
    _, dao = install_context(gateway)

    with SimpleTestClient(app) as client:
        res = client.post(
            "/admin/artists/spotify:alpha/reconcile",
            params={"dry_run": "true"},
            use_raw_path=True,
        )

    assert res.status_code == 200
    body = res.json()
    assert body["dryRun"] is True
    assert body["applied"] is False
    assert body["delta"]["summary"]["added"] == 1
    assert dao.get_artist("spotify:alpha") is None


def test_admin_apply_reconcile_updates_and_audits(
    install_context: Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]],
) -> None:
    response = _make_gateway_response([_make_release()])
    gateway = StubGateway(response)
    _, dao = install_context(gateway)

    with SimpleTestClient(app) as client:
        res = client.post(
            "/admin/artists/spotify:alpha/reconcile",
            params={"dry_run": "false"},
            use_raw_path=True,
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["applied"] is True

        audit = client.get(
            "/admin/artists/spotify:alpha/audit",
            params={"limit": 10},
            use_raw_path=True,
        )
        assert audit.status_code == 200
        assert audit.json()["items"], "expected audit events after reconcile"

    artist_row = dao.get_artist("spotify:alpha")
    assert artist_row is not None
    releases = dao.get_artist_releases("spotify:alpha")
    assert len(releases) == 1


def test_admin_resync_enqueues_with_priority_and_lock_guard(
    install_context: Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]],
) -> None:
    response = _make_gateway_response([])
    gateway = StubGateway(response)
    install_context(gateway)

    with SimpleTestClient(app) as client:
        res = client.post(
            "/admin/artists/spotify:alpha/resync",
            use_raw_path=True,
        )
        assert res.status_code == 200
        payload = res.json()
        expected_priority = app_settings.orchestrator.priority_map.get("sync", 0) + 10
        assert payload["priority"] == expected_priority
        job_id = payload["jobId"]

    with session_scope() as session:
        job = session.get(QueueJob, int(job_id))
        assert job is not None
        assert job.priority == expected_priority
        assert job.payload.get("force_resync") is True
        job.status = QueueJobStatus.LEASED.value
        job.lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
        session.add(job)

    with SimpleTestClient(app) as client:
        blocked = client.post(
            "/admin/artists/spotify:alpha/resync",
            use_raw_path=True,
        )
        assert blocked.status_code == 409
        detail = blocked.json()
        assert detail["error"]["message"] == "Artist is currently being processed."
        assert detail["error"].get("meta", {}).get("job_id") == int(job_id)


def test_admin_audit_lists_recent_events_paginated(
    install_context: Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]],
) -> None:
    response = _make_gateway_response(
        [_make_release(), _make_release(source_id="rel-2", title="Second")]
    )
    gateway = StubGateway(response)
    install_context(gateway)

    with SimpleTestClient(app) as client:
        client.post(
            "/admin/artists/spotify:alpha/reconcile",
            params={"dry_run": "false"},
            use_raw_path=True,
        )
        first = client.get(
            "/admin/artists/spotify:alpha/audit",
            params={"limit": 1},
            use_raw_path=True,
        )
        assert first.status_code == 200
        payload = first.json()
        assert payload["items"]
        cursor = payload["nextCursor"]
        if cursor is not None:
            second = client.get(
                "/admin/artists/spotify:alpha/audit",
                params={"limit": 1, "cursor": cursor},
                use_raw_path=True,
            )
            assert second.status_code == 200


def test_admin_invalidate_busts_cache_etag(
    install_context: Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]],
) -> None:
    response = _make_gateway_response([])
    gateway = StubGateway(response)
    cache = ResponseCache(max_items=8, default_ttl=60, write_through=True, log_evictions=False)
    app.state.response_cache = cache
    install_context(gateway, cache=cache)

    key = build_cache_key(
        method="GET",
        path_template="/artists/{artist_key}",
        query_string="",
        path_params={"artist_key": "spotify:alpha"},
        auth_variant="anon",
    )
    entry = CacheEntry(
        key="",
        path_template="/artists/{artist_key}",
        status_code=200,
        body=b"{}",
        headers={},
        media_type="application/json",
        etag='"etag"',
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        last_modified_ts=0,
        cache_control="max-age=60",
        vary=(),
        created_at=0.0,
        expires_at=None,
        ttl=60.0,
        stale_while_revalidate=None,
        stale_expires_at=None,
    )
    with SimpleTestClient(app) as client:
        client._loop.run_until_complete(cache.set(key, entry))
        res = client.post(
            "/admin/artists/spotify:alpha/invalidate",
            use_raw_path=True,
        )
        assert res.status_code == 200
        assert res.json()["evicted"] == 1


def test_admin_safety_checks_retry_budget_and_staleness(
    monkeypatch: pytest.MonkeyPatch,
    install_context: Callable[[StubGateway, ResponseCache | None], tuple[AdminContext, ArtistDao]],
) -> None:
    monkeypatch.setenv("ARTIST_STALENESS_MAX_MIN", "1")
    monkeypatch.setenv("ARTIST_RETRY_BUDGET_MAX", "1")
    deps.get_app_config.cache_clear()
    maybe_register_admin_routes(app, config=deps.get_app_config())

    response = _make_gateway_response([_make_release(title="Fresh")])
    gateway = StubGateway(response)
    _, dao = install_context(gateway)

    artist_dto = ArtistUpsertDTO(
        artist_key="spotify:alpha",
        source="spotify",
        source_id="alpha",
        name="Alpha",
    )
    dao.upsert_artist(artist_dto)
    dao.upsert_releases(
        [
            ArtistReleaseUpsertDTO(
                artist_key="spotify:alpha",
                source="spotify",
                source_id="old-rel",
                title="Old Release",
            )
        ]
    )
    with session_scope() as session:
        artist = session.query(ArtistRecord).filter_by(artist_key="spotify:alpha").first()
        assert artist is not None
        artist.updated_at = datetime.utcnow() - timedelta(minutes=10)
        session.add(artist)
        release = (
            session.query(ArtistReleaseRecord)
            .filter_by(artist_key="spotify:alpha", source_id="old-rel")
            .first()
        )
        assert release is not None
        release.updated_at = datetime.utcnow() - timedelta(minutes=10)
        session.add(release)

    with SimpleTestClient(app) as client:
        dry_run = client.post(
            "/admin/artists/spotify:alpha/reconcile",
            params={"dry_run": "true"},
            use_raw_path=True,
        )
        assert dry_run.status_code == 200
        safety = dry_run.json()["safety"]
        assert safety["stale"] is True

    with session_scope() as session:
        job = QueueJob(
            type="artist_sync",
            status=QueueJobStatus.PENDING.value,
            payload={"artist_key": "spotify:alpha"},
            priority=0,
            attempts=1,
            available_at=datetime.utcnow(),
        )
        session.add(job)

    with SimpleTestClient(app) as client:
        blocked = client.post(
            "/admin/artists/spotify:alpha/reconcile",
            params={"dry_run": "false"},
            use_raw_path=True,
        )
        assert blocked.status_code == 429
        detail = blocked.json()
        assert detail["error"]["code"] == "RATE_LIMITED"
        assert detail["error"]["message"] == "Retry budget exhausted for this artist."
        assert detail["error"].get("meta") == {"attempts": 1, "budget": 1}
