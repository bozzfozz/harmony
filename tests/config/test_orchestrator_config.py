from __future__ import annotations

import json

from app.config import DEFAULT_ORCH_PRIORITY_MAP, OrchestratorConfig


def test_priority_json_and_csv_fallback() -> None:
    json_env = {"ORCH_PRIORITY_JSON": json.dumps({"sync": 70, "retry": 30})}
    config = OrchestratorConfig.from_env(json_env)
    assert config.priority_map["sync"] == 70
    assert config.priority_map["retry"] == 30

    csv_env = {
        "ORCH_PRIORITY_JSON": "not-json",
        "ORCH_PRIORITY_CSV": "matching:40,watchlist:10",
    }
    csv_config = OrchestratorConfig.from_env(csv_env)
    assert csv_config.priority_map == {"matching": 40, "watchlist": 10}

    default_config = OrchestratorConfig.from_env({})
    assert default_config.priority_map == DEFAULT_ORCH_PRIORITY_MAP


def test_bounds_and_defaults_applied() -> None:
    env = {
        "ORCH_GLOBAL_CONCURRENCY": "0",
        "ORCH_POOL_SYNC": "0",
        "ORCH_POOL_MATCHING": "-5",
        "ORCH_POOL_RETRY": "-1",
        "ORCH_POOL_WATCHLIST": "3",
        "ORCH_VISIBILITY_TIMEOUT_S": "2",
        "ORCH_HEARTBEAT_S": "-10",
        "ORCH_POLL_INTERVAL_MS": "5",
    }
    config = OrchestratorConfig.from_env(env)

    assert config.global_concurrency == 1
    assert config.pool_sync == 1
    assert config.pool_matching == 1
    assert config.pool_retry == 1
    assert config.pool_watchlist == 3
    assert config.visibility_timeout_s == 5
    assert config.heartbeat_s == 1
    assert config.poll_interval_ms == 10
