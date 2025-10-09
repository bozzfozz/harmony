"""Runtime retry policy provider with TTL-based caching."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.config import (
    DEFAULT_RETRY_BASE_SECONDS,
    DEFAULT_RETRY_JITTER_PCT,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_POLICY_RELOAD_S,
    get_runtime_env,
)
from app.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_JOB_KEY = "__default__"
_JOB_TYPE_SANITIZER = re.compile(r"[^A-Z0-9]+")


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """Resolved retry policy describing backoff and limits."""

    max_attempts: int
    base_seconds: float
    jitter_pct: float
    timeout_seconds: float | None = None


@dataclass(slots=True)
class _CacheEntry:
    policy: RetryPolicy
    expires_at: float


def _parse_positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    return parsed


def _parse_positive_float(value: Any, default: float, *, minimum: float = 1e-3) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    return parsed


def _parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_jitter(value: Any, default_pct: float) -> float:
    if value is None:
        resolved = default_pct
    else:
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            resolved = default_pct
    if resolved < 0:
        return 0.0
    if resolved <= 1:
        return resolved
    return resolved / 100.0


def _normalise_job_type(job_type: str | None) -> str:
    if not job_type:
        return _DEFAULT_JOB_KEY
    upper = job_type.upper()
    return _JOB_TYPE_SANITIZER.sub("_", upper).strip("_") or _DEFAULT_JOB_KEY


class RetryPolicyProvider:
    """Provide retry policies that refresh from the environment on a TTL."""

    def __init__(
        self,
        *,
        reload_interval: float | None = None,
        env_source: Callable[[], Mapping[str, Any]] | None = None,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        self._env_source = env_source or (lambda: get_runtime_env())
        self._time_source = time_source or time.monotonic
        self._lock = threading.RLock()
        self._reload_override = reload_interval
        initial_env = dict(self._env_source())
        self._reload_interval = self._resolve_reload_interval(initial_env)
        self._cache: dict[str, _CacheEntry] = {}

    @property
    def reload_interval(self) -> float:
        """Return the currently active cache TTL in seconds."""

        with self._lock:
            return self._reload_interval

    def get_retry_policy(self, job_type: str | None = None) -> RetryPolicy:
        """Return the retry policy for the given job type honoring the TTL."""

        cache_key = _normalise_job_type(job_type)
        now = self._time_source()

        with self._lock:
            ttl = self._reload_interval
            if ttl > 0:
                entry = self._cache.get(cache_key)
                if entry is not None and entry.expires_at > now:
                    return entry.policy

        policy, expiry, resolved_ttl = self._load_policy(cache_key, job_type)

        with self._lock:
            self._reload_interval = resolved_ttl
            if resolved_ttl > 0:
                self._cache[cache_key] = _CacheEntry(policy=policy, expires_at=expiry)
            else:
                self._cache.pop(cache_key, None)
        return policy

    def invalidate(self, job_type: str | None = None) -> None:
        """Clear cached policies either for a job type or entirely."""

        cache_key = _normalise_job_type(job_type)
        with self._lock:
            if job_type is None:
                self._cache.clear()
            else:
                self._cache.pop(cache_key, None)

    def _load_policy(
        self, cache_key: str, job_type: str | None
    ) -> tuple[RetryPolicy, float, float]:
        env_snapshot = dict(self._env_source())
        resolved_ttl = self._resolve_reload_interval(env_snapshot)
        policy = self._parse_policy(env_snapshot, cache_key, job_type)
        now = self._time_source()
        expires = now + resolved_ttl if resolved_ttl > 0 else now
        return policy, expires, resolved_ttl

    def _resolve_reload_interval(self, env: Mapping[str, Any]) -> float:
        if self._reload_override is not None:
            try:
                override = float(self._reload_override)
            except (TypeError, ValueError):
                override = DEFAULT_RETRY_POLICY_RELOAD_S
            return max(0.0, override)

        raw = env.get("RETRY_POLICY_RELOAD_S")
        if raw is None:
            return DEFAULT_RETRY_POLICY_RELOAD_S
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            logger.warning("invalid reload interval for retry policy", extra={"value": raw})
            return DEFAULT_RETRY_POLICY_RELOAD_S
        if parsed < 0:
            return DEFAULT_RETRY_POLICY_RELOAD_S
        return parsed

    def _parse_policy(
        self, env: Mapping[str, Any], cache_key: str, job_type: str | None
    ) -> RetryPolicy:
        overrides = self._apply_job_overrides(dict(env), cache_key)
        max_attempts = _parse_positive_int(
            overrides.get("RETRY_MAX_ATTEMPTS"), DEFAULT_RETRY_MAX_ATTEMPTS
        )
        base_seconds = _parse_positive_float(
            overrides.get("RETRY_BASE_SECONDS"), DEFAULT_RETRY_BASE_SECONDS
        )
        jitter_pct = _parse_jitter(overrides.get("RETRY_JITTER_PCT"), DEFAULT_RETRY_JITTER_PCT)
        timeout_seconds = _parse_optional_float(overrides.get("RETRY_TIMEOUT_SECONDS"))
        return RetryPolicy(
            max_attempts=max_attempts,
            base_seconds=base_seconds,
            jitter_pct=jitter_pct,
            timeout_seconds=timeout_seconds,
        )

    def _apply_job_overrides(self, env: dict[str, Any], cache_key: str) -> dict[str, Any]:
        if cache_key == _DEFAULT_JOB_KEY:
            return env

        suffixes = {
            "MAX_ATTEMPTS": "RETRY_MAX_ATTEMPTS",
            "BASE_SECONDS": "RETRY_BASE_SECONDS",
            "JITTER_PCT": "RETRY_JITTER_PCT",
            "TIMEOUT_SECONDS": "RETRY_TIMEOUT_SECONDS",
        }
        prefix = cache_key
        for suffix, target_key in suffixes.items():
            specific_key = f"RETRY_{prefix}_{suffix}"
            if specific_key in env:
                env[target_key] = env[specific_key]
        return env


_default_provider = RetryPolicyProvider()


def get_retry_policy(job_type: str | None = None) -> RetryPolicy:
    """Return the retry policy for the given job type using the shared provider."""

    return _default_provider.get_retry_policy(job_type)


def get_retry_policy_provider() -> RetryPolicyProvider:
    """Expose the shared provider instance (primarily for tests)."""

    return _default_provider
