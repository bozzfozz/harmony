from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("SLSKD_API_KEY", "test-key")

from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_app_config
from app.main import app


def test_env_endpoint_exposes_configuration() -> None:
    client = TestClient(app)
    response = client.get("/env")

    assert response.status_code == 200

    payload = response.json()
    config_snapshot = get_app_config()

    assert payload["api_base_path"] == config_snapshot.api_base_path

    features = payload["feature_flags"]
    assert features["enable_artwork"] == config_snapshot.features.enable_artwork
    assert features["enable_lyrics"] == config_snapshot.features.enable_lyrics
    assert (
        features["enable_legacy_routes"]
        == config_snapshot.features.enable_legacy_routes
    )
    assert (
        features["enable_artist_cache_invalidation"]
        == config_snapshot.features.enable_artist_cache_invalidation
    )
    assert features["enable_admin_api"] == config_snapshot.features.enable_admin_api

    environment = payload["environment"]
    assert environment["profile"] == config_snapshot.environment.profile
    assert environment["is_dev"] == config_snapshot.environment.is_dev
    assert environment["is_test"] == config_snapshot.environment.is_test
    assert environment["is_prod"] == config_snapshot.environment.is_prod

    workers = environment["workers"]
    assert workers["disable_workers"] == config_snapshot.environment.workers.disable_workers
    assert (
        workers["enabled_override"]
        == config_snapshot.environment.workers.enabled_override
    )
    assert workers["enabled_raw"] == config_snapshot.environment.workers.enabled_raw
    assert (
        workers["visibility_timeout_s"]
        == config_snapshot.environment.workers.visibility_timeout_s
    )
    assert (
        workers["watchlist_interval_s"]
        == config_snapshot.environment.workers.watchlist_interval_s
    )
    assert (
        workers["watchlist_timer_enabled"]
        == config_snapshot.environment.workers.watchlist_timer_enabled
    )

    orchestrator = payload["orchestrator"]
    assert orchestrator["workers_enabled"] == settings.orchestrator.workers_enabled
    assert orchestrator["global_concurrency"] == settings.orchestrator.global_concurrency
    assert (
        orchestrator["visibility_timeout_s"]
        == settings.orchestrator.visibility_timeout_s
    )
    assert orchestrator["poll_interval_ms"] == settings.orchestrator.poll_interval_ms
    assert (
        orchestrator["poll_interval_max_ms"]
        == settings.orchestrator.poll_interval_max_ms
    )
    assert orchestrator["priority_map"] == dict(settings.orchestrator.priority_map)

    watchlist = payload["watchlist_timer"]
    assert watchlist["enabled"] == settings.watchlist_timer.enabled
    assert watchlist["interval_s"] == settings.watchlist_timer.interval_s

    build = payload["build"]
    assert build["version"] == app.version
    started_at = build["started_at"]
    # ``datetime.fromisoformat`` requires ``+00:00`` rather than ``Z``.
    normalized_started_at = started_at.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized_started_at)
    assert parsed.tzinfo is not None
