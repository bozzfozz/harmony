from __future__ import annotations

import asyncio
import random
from typing import Any, Callable, Mapping

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.orchestrator.handlers import SyncHandlerDeps, handle_sync_download_failure
from app.services.retry_policy_provider import RetryPolicyProvider


class _StubSoulseekClient:
    pass


def _env_source_factory(env: Mapping[str, Any]) -> Callable[[], Mapping[str, Any]]:
    return lambda env_map=env: env_map


def test_retry_provider_reload_after_ttl_applies_new_env(monkeypatch: pytest.MonkeyPatch) -> None:
    env: dict[str, Any] = {
        "RETRY_MAX_ATTEMPTS": "2",
        "RETRY_BASE_SECONDS": "1",
        "RETRY_JITTER_PCT": "0",
        "RETRY_POLICY_RELOAD_S": "0.1",
    }
    now = [0.0]

    def fake_time() -> float:
        return now[0]

    provider = RetryPolicyProvider(
        env_source=_env_source_factory(env),
        time_source=fake_time,
    )

    policy = provider.get_retry_policy()
    assert policy.max_attempts == 2

    env["RETRY_MAX_ATTEMPTS"] = "4"
    unchanged = provider.get_retry_policy()
    assert unchanged.max_attempts == 2

    now[0] += 0.2
    refreshed = provider.get_retry_policy()
    assert refreshed.max_attempts == 4


def test_retry_provider_typ_specific_overrides_fallbacks() -> None:
    env: dict[str, Any] = {
        "RETRY_MAX_ATTEMPTS": "5",
        "RETRY_BASE_SECONDS": "2.5",
        "RETRY_JITTER_PCT": "0.1",
        "RETRY_SYNC_MAX_ATTEMPTS": "7",
        "RETRY_MATCHING_BASE_SECONDS": "3.0",
    }
    provider = RetryPolicyProvider(env_source=_env_source_factory(env), reload_interval=0)

    default_policy = provider.get_retry_policy()
    assert default_policy.max_attempts == 5
    assert pytest.approx(default_policy.base_seconds) == 2.5

    sync_policy = provider.get_retry_policy("sync")
    assert sync_policy.max_attempts == 7
    assert pytest.approx(sync_policy.base_seconds) == 2.5

    matching_policy = provider.get_retry_policy("matching")
    assert matching_policy.max_attempts == 5
    assert pytest.approx(matching_policy.base_seconds) == 3.0


def test_handler_uses_updated_policy_without_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import retry_policy_provider as provider_module
    from app.orchestrator.handlers import load_sync_retry_policy

    env: dict[str, Any] = {
        "RETRY_MAX_ATTEMPTS": "2",
        "RETRY_BASE_SECONDS": "1",
        "RETRY_JITTER_PCT": "0",
        "RETRY_POLICY_RELOAD_S": "0.1",
    }
    now = [0.0]

    def fake_time() -> float:
        return now[0]

    provider = RetryPolicyProvider(
        env_source=_env_source_factory(env),
        time_source=fake_time,
    )
    monkeypatch.setattr(provider_module, "_default_provider", provider)

    initial = load_sync_retry_policy()
    assert initial.max_attempts == 2

    env["RETRY_MAX_ATTEMPTS"] = "5"
    cached = load_sync_retry_policy()
    assert cached.max_attempts == 2

    now[0] += 0.2
    refreshed = load_sync_retry_policy()
    assert refreshed.max_attempts == 5


def test_dlq_after_max_attempts_update(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import retry_policy_provider as provider_module

    reset_engine_for_tests()
    init_db()

    env: dict[str, Any] = {
        "RETRY_MAX_ATTEMPTS": "3",
        "RETRY_BASE_SECONDS": "1",
        "RETRY_JITTER_PCT": "0",
        "RETRY_POLICY_RELOAD_S": "0.1",
    }
    now = [0.0]

    def fake_time() -> float:
        return now[0]

    provider = RetryPolicyProvider(
        env_source=_env_source_factory(env),
        time_source=fake_time,
    )
    monkeypatch.setattr(provider_module, "_default_provider", provider)

    with session_scope() as session:
        download = Download(
            filename="retry-me.mp3",
            state="failed",
            progress=0.0,
            priority=1,
            username="tester",
            retry_count=0,
        )
        session.add(download)
        session.flush()
        download_id = int(download.id)

    deps = SyncHandlerDeps(soulseek_client=_StubSoulseekClient(), rng=random.Random(0))
    job = {"username": "tester"}
    files = [{"download_id": download_id}]

    # First failure schedules a retry under initial policy.
    now[0] += 0.2
    asyncio.run(handle_sync_download_failure(job, files, deps, "boom"))

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.next_retry_at is not None
        first_retry_count = int(refreshed.retry_count)
        assert first_retry_count == 1

    # Tighten policy and wait for TTL so the next load observes the new value.
    env["RETRY_MAX_ATTEMPTS"] = "1"
    now[0] += 0.2

    asyncio.run(handle_sync_download_failure(job, files, deps, "boom again"))

    with session_scope() as session:
        exhausted = session.get(Download, download_id)
        assert exhausted is not None
        assert exhausted.state == "dead_letter"
        assert exhausted.next_retry_at is None
