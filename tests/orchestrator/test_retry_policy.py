"""Tests for orchestrator retry policy configuration reloading."""

from __future__ import annotations

from app.orchestrator import handlers


def test_retry_policy_respects_environment_overrides(monkeypatch) -> None:
    """Environment changes should take effect on the next policy load."""

    monkeypatch.delenv("RETRY_MAX_ATTEMPTS", raising=False)
    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "3")

    first_policy = handlers.load_sync_retry_policy()
    assert first_policy.max_attempts == 3

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "7")

    updated_policy = handlers.load_sync_retry_policy()
    assert updated_policy.max_attempts == 7
