from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.ui.session import (
    UiLoginRateLimitConfig,
    UiLoginRateLimiter,
    UiLoginRateLimitError,
)


class InMemoryLoginAttemptStore:
    """Minimal in-memory store emulating ``UiLoginAttemptStore`` semantics."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str], list[datetime]] = {}

    def count_recent_attempts(
        self,
        scope: str,
        key: str,
        *,
        now: datetime,
        window: timedelta,
    ) -> tuple[int, datetime | None]:
        entries = self._prune(scope, key, now - window)
        if not entries:
            return 0, None
        return len(entries), entries[0]

    def record_attempt(
        self,
        scope: str,
        key: str,
        *,
        now: datetime,
        window: timedelta,
    ) -> tuple[int, datetime | None]:
        entries = self._prune(scope, key, now - window)
        entries.append(now)
        entries.sort()
        self._attempts[(scope, key)] = entries
        return len(entries), entries[0]

    def seed(self, scope: str, key: str, timestamps: list[datetime]) -> None:
        ordered = sorted(timestamps)
        self._attempts[(scope, key)] = ordered

    def _prune(self, scope: str, key: str, cutoff: datetime) -> list[datetime]:
        entries = [ts for ts in self._attempts.get((scope, key), []) if ts >= cutoff]
        self._attempts[(scope, key)] = entries
        return entries


@dataclass(slots=True)
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float = 0.0) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.fixture()
def limiter_fixture(monkeypatch: pytest.MonkeyPatch):
    store = InMemoryLoginAttemptStore()
    config = UiLoginRateLimitConfig(attempts=3, window=timedelta(seconds=60))
    clock = FakeClock(current=datetime(2024, 1, 1, tzinfo=UTC))
    monkeypatch.setattr("app.ui.session._utcnow", clock.now)
    limiter = UiLoginRateLimiter(store=store, config=config)
    return limiter, store, clock, config


def test_ensure_can_attempt_allows_within_budget(limiter_fixture) -> None:
    limiter, _, clock, config = limiter_fixture
    remote = "127.0.0.1"
    fingerprint = "fingerprint"

    for _ in range(config.attempts):
        limiter.ensure_can_attempt(remote, fingerprint)
        limiter.record_failure(remote, fingerprint)
        clock.advance(seconds=10)


def test_ensure_can_attempt_blocks_after_budget(limiter_fixture) -> None:
    limiter, store, clock, config = limiter_fixture
    remote = "127.0.0.1"
    fingerprint = "fingerprint"

    for _ in range(config.attempts):
        limiter.record_failure(remote, fingerprint)
        clock.advance(seconds=10)

    with pytest.raises(UiLoginRateLimitError) as exc:
        limiter.ensure_can_attempt(remote, fingerprint)

    now = clock.now()
    count, oldest = store.count_recent_attempts(
        "remote",
        remote,
        now=now,
        window=config.window,
    )
    assert count == config.attempts
    assert oldest is not None
    expected_remaining = config.window.total_seconds() - (now - oldest).total_seconds()
    assert exc.value.retry_after == pytest.approx(expected_remaining)


def test_record_failure_raises_with_combined_scopes(limiter_fixture) -> None:
    limiter, store, clock, _ = limiter_fixture
    remote = "127.0.0.1"
    fingerprint = "fingerprint"
    base = clock.now()

    store.seed(
        "remote",
        remote,
        [
            base - timedelta(seconds=30),
            base - timedelta(seconds=20),
            base - timedelta(seconds=10),
        ],
    )
    store.seed(
        "fingerprint",
        fingerprint,
        [
            base - timedelta(seconds=15),
            base - timedelta(seconds=12),
            base - timedelta(seconds=5),
        ],
    )

    with pytest.raises(UiLoginRateLimitError) as exc:
        limiter.record_failure(remote, fingerprint)

    assert exc.value.retry_after == pytest.approx(45.0)
