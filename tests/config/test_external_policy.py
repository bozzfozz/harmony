from __future__ import annotations

from app.config import ExternalCallPolicy


def test_retry_backoff_jitter_values() -> None:
    env = {
        "EXTERNAL_TIMEOUT_MS": "150",
        "EXTERNAL_RETRY_MAX": "-1",
        "EXTERNAL_BACKOFF_BASE_MS": "0",
        "EXTERNAL_JITTER_PCT": "30",
    }
    policy = ExternalCallPolicy.from_env(env)

    assert policy.timeout_ms == 150
    assert policy.retry_max == 0
    assert policy.backoff_base_ms == 1
    assert policy.jitter_pct == 0.3


def test_jitter_accepts_fractional_input() -> None:
    env = {"EXTERNAL_JITTER_PCT": "0.05"}
    policy = ExternalCallPolicy.from_env(env)

    assert policy.jitter_pct == 0.05
