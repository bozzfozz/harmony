"""Tests for orchestrator priority configuration parsing."""

from __future__ import annotations

import json

from app.orchestrator.scheduler import PriorityConfig


def test_priority_config_prefers_json_payload() -> None:
    payload = {"sync": 100, "matching": "60", "retry": 5}
    env: dict[str, str] = {"ORCH_PRIORITY_JSON": json.dumps(payload)}

    config = PriorityConfig.from_env(env)

    assert config.priorities == {"sync": 100, "matching": 60, "retry": 5}
    assert config.job_types == ("sync", "matching", "retry")


def test_priority_config_invalid_json_falls_back_to_csv() -> None:
    env = {
        "ORCH_PRIORITY_JSON": "{not valid",
        "ORCH_PRIORITY_CSV": "sync:10, retry:5, matching:5",
    }

    config = PriorityConfig.from_env(env)

    assert config.priorities == {"sync": 10, "retry": 5, "matching": 5}
    # matching and retry share a priority value, alphabetical order decides
    assert config.job_types == ("sync", "matching", "retry")


def test_priority_config_csv_parser_ignores_invalid_entries() -> None:
    env = {"ORCH_PRIORITY_CSV": "sync:10, invalid, :5, retry:foo, matching:15"}

    config = PriorityConfig.from_env(env)

    assert config.priorities == {"sync": 10, "matching": 15, "retry": 0}
    assert config.job_types == ("matching", "sync", "retry")
