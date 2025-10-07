from __future__ import annotations

import json

from app.config import DEFAULT_ORCH_PRIORITY_MAP, OrchestratorConfig, Settings, load_config
from app.orchestrator import handlers as orchestrator_handlers


def test_priority_json_and_csv_fallback() -> None:
    json_env = {"ORCH_PRIORITY_JSON": json.dumps({"sync": 70, "retry": 30})}
    config = OrchestratorConfig.from_env(json_env)
    assert config.priority_map["sync"] == 70
    assert config.priority_map["retry"] == 30

    csv_env = {
        "ORCH_PRIORITY_JSON": "not-json",
        "ORCH_PRIORITY_CSV": "matching:40,artist_refresh:10",
    }
    csv_config = OrchestratorConfig.from_env(csv_env)
    assert csv_config.priority_map == {"matching": 40, "artist_refresh": 10}

    default_config = OrchestratorConfig.from_env({})
    assert default_config.priority_map == DEFAULT_ORCH_PRIORITY_MAP


def test_bounds_and_defaults_applied() -> None:
    env = {
        "ORCH_GLOBAL_CONCURRENCY": "0",
        "ORCH_POOL_SYNC": "0",
        "ORCH_POOL_MATCHING": "-5",
        "ORCH_POOL_RETRY": "-1",
        "ORCH_POOL_ARTIST_REFRESH": "3",
        "ORCH_POOL_ARTIST_DELTA": "4",
        "ORCH_VISIBILITY_TIMEOUT_S": "2",
        "ORCH_HEARTBEAT_S": "-10",
        "ORCH_POLL_INTERVAL_MS": "5",
    }
    config = OrchestratorConfig.from_env(env)

    assert config.global_concurrency == 1
    assert config.pool_sync == 1
    assert config.pool_matching == 1
    assert config.pool_retry == 1
    assert config.pool_artist_refresh == 3
    assert config.pool_artist_delta == 4
    assert config.visibility_timeout_s == 5
    assert config.heartbeat_s == 1
    assert config.poll_interval_ms == 10


def test_artist_pool_and_priority_overrides() -> None:
    env = {
        "ARTIST_POOL_CONCURRENCY": "5",
        "ARTIST_PRIORITY": "88",
    }
    config = OrchestratorConfig.from_env(env)

    assert config.pool_artist_refresh == 5
    assert config.pool_artist_delta == 5
    assert config.priority_map["artist_refresh"] == 88
    assert config.priority_map["artist_delta"] == 88


def test_settings_retry_policy_from_env() -> None:
    env = {
        "RETRY_MAX_ATTEMPTS": "7",
        "RETRY_BASE_SECONDS": "120",
        "RETRY_JITTER_PCT": "50",
    }
    config = Settings.load(env)

    assert config.retry_policy.max_attempts == 7
    assert config.retry_policy.base_seconds == 120.0
    assert config.retry_policy.jitter_pct == 0.5


def test_load_sync_retry_policy_uses_settings(monkeypatch) -> None:
    env = {
        "RETRY_MAX_ATTEMPTS": "4",
        "RETRY_BASE_SECONDS": "45",
        "RETRY_JITTER_PCT": "10",
    }
    config = Settings.load(env)

    policy = orchestrator_handlers.load_sync_retry_policy(defaults=config.retry_policy)

    assert policy.max_attempts == 4
    assert policy.base_seconds == 45.0
    assert policy.jitter_pct == 0.1


def test_load_config_exposes_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "true")
    monkeypatch.setenv("WORKER_VISIBILITY_TIMEOUT_S", "75")
    monkeypatch.setenv("WATCHLIST_INTERVAL", "123.5")
    monkeypatch.setenv("WATCHLIST_TIMER_ENABLED", "0")

    config = load_config()
    environment = config.environment

    assert environment.profile == "prod"
    assert environment.is_prod is True
    assert environment.is_dev is False
    assert environment.workers.disable_workers is True
    assert environment.workers.visibility_timeout_s == 75
    assert environment.workers.watchlist_interval_s == 123.5
    assert environment.workers.watchlist_timer_enabled is False
