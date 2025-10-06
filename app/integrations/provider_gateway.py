"""Gateway orchestrating provider calls with shared policies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Sequence

from app.config import ExternalCallPolicy, ProviderProfile, settings
from app.integrations.contracts import (
    ProviderDependencyError,
    ProviderError,
    ProviderInternalError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderTrack,
    ProviderValidationError,
    SearchQuery,
    TrackProvider,
)
from app.logging import get_logger
from app.logging_events import log_event
from app.utils.retry import RetryDirective, with_retry


logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class ProviderRetryPolicy:
    """Retry and timeout behaviour for a provider."""

    timeout_ms: int
    retry_max: int
    backoff_base_ms: int
    jitter_pct: float

    @classmethod
    def from_external(cls, policy: ExternalCallPolicy) -> "ProviderRetryPolicy":
        """Create a retry policy from the shared external call policy."""

        return cls(
            timeout_ms=max(100, policy.timeout_ms),
            retry_max=max(0, policy.retry_max),
            backoff_base_ms=max(1, policy.backoff_base_ms),
            jitter_pct=max(0.0, policy.jitter_pct),
        )


@dataclass(slots=True, frozen=True)
class ProviderGatewayConfig:
    """Runtime configuration for the provider gateway."""

    max_concurrency: int
    default_policy: ProviderRetryPolicy
    provider_policies: Mapping[str, ProviderRetryPolicy]

    def policy_for(self, provider: str) -> ProviderRetryPolicy:
        return self.provider_policies.get(provider, self.default_policy)

    @classmethod
    def from_settings(
        cls,
        *,
        max_concurrency: int,
        external_policy: ExternalCallPolicy | None = None,
        provider_profiles: Mapping[str, ProviderProfile] | None = None,
    ) -> "ProviderGatewayConfig":
        """Create a gateway configuration backed by centralised settings."""

        external = external_policy or settings.external
        profiles = provider_profiles or settings.provider_profiles
        default_policy = ProviderRetryPolicy.from_external(external)
        provider_policies: dict[str, ProviderRetryPolicy] = {}
        for name, profile in profiles.items():
            provider_policies[name.lower()] = ProviderRetryPolicy.from_external(profile.policy)
        return cls(
            max_concurrency=max(1, max_concurrency),
            default_policy=default_policy,
            provider_policies=provider_policies,
        )


class ProviderGatewayError(RuntimeError):
    """Base class for gateway level failures."""

    def __init__(self, provider: str, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.cause = cause


class ProviderGatewayTimeoutError(ProviderGatewayError):
    def __init__(self, provider: str, timeout_ms: int, *, cause: Exception | None = None) -> None:
        super().__init__(provider, f"{provider} timed out after {timeout_ms}ms", cause=cause)
        self.timeout_ms = timeout_ms


class ProviderGatewayValidationError(ProviderGatewayError):
    def __init__(
        self, provider: str, *, status_code: int | None, cause: Exception | None = None
    ) -> None:
        super().__init__(provider, f"{provider} rejected the request", cause=cause)
        self.status_code = status_code


class ProviderGatewayRateLimitedError(ProviderGatewayError):
    def __init__(
        self,
        provider: str,
        *,
        retry_after_ms: int | None,
        retry_after_header: str | None,
        cause: Exception | None = None,
        status_code: int | None,
    ) -> None:
        super().__init__(provider, f"{provider} rate limited the request", cause=cause)
        self.retry_after_ms = retry_after_ms
        self.retry_after_header = retry_after_header
        self.status_code = status_code


class ProviderGatewayNotFoundError(ProviderGatewayError):
    def __init__(
        self, provider: str, *, status_code: int | None, cause: Exception | None = None
    ) -> None:
        super().__init__(provider, f"{provider} returned no results", cause=cause)
        self.status_code = status_code


class ProviderGatewayDependencyError(ProviderGatewayError):
    def __init__(
        self, provider: str, *, status_code: int | None, cause: Exception | None = None
    ) -> None:
        super().__init__(provider, f"{provider} dependency failure", cause=cause)
        self.status_code = status_code


class ProviderGatewayInternalError(ProviderGatewayError):
    pass


@dataclass(slots=True, frozen=True)
class ProviderGatewaySearchResult:
    """Container describing the outcome of a single provider call."""

    provider: str
    tracks: tuple[ProviderTrack, ...]
    error: ProviderGatewayError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(slots=True, frozen=True)
class ProviderGatewaySearchResponse:
    """Aggregated response for multi-provider search operations."""

    results: tuple[ProviderGatewaySearchResult, ...]

    @property
    def tracks(self) -> tuple[ProviderTrack, ...]:
        aggregated: list[ProviderTrack] = []
        for result in self.results:
            aggregated.extend(result.tracks)
        return tuple(aggregated)

    @property
    def errors(self) -> Mapping[str, ProviderGatewayError]:
        failures: dict[str, ProviderGatewayError] = {}
        for result in self.results:
            if result.error is not None:
                failures[result.provider] = result.error
        return failures

    @property
    def status(self) -> str:
        if not self.results:
            return "ok"
        successes = sum(1 for result in self.results if result.ok)
        if successes == len(self.results):
            return "ok"
        if successes == 0:
            return "failed"
        return "partial"


class ProviderGateway:
    """Coordinates provider calls and normalises failures."""

    def __init__(
        self,
        *,
        providers: Mapping[str, TrackProvider],
        config: ProviderGatewayConfig,
    ) -> None:
        self._providers = {name.lower(): provider for name, provider in providers.items()}
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    async def search_tracks(self, provider: str, query: SearchQuery) -> list[ProviderTrack]:
        response = await self._search_provider(provider, query)
        if response.error is not None:
            raise response.error
        return list(response.tracks)

    async def search_many(
        self, providers: Sequence[str], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        if not providers:
            return ProviderGatewaySearchResponse(results=())

        async def _run(name: str) -> ProviderGatewaySearchResult:
            return await self._search_provider(name, query)

        provider_list = list(providers)
        tasks = [asyncio.create_task(_run(provider)) for provider in provider_list]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[ProviderGatewaySearchResult] = []
        for name, item in zip(provider_list, gathered):
            if isinstance(item, ProviderGatewaySearchResult):
                results.append(item)
                continue
            if isinstance(item, Exception):
                logger.exception("Provider task failed", exc_info=item)
            results.append(
                ProviderGatewaySearchResult(
                    provider=name,
                    tracks=tuple(),
                    error=ProviderGatewayInternalError(name, "unexpected task failure"),
                )
            )
        return ProviderGatewaySearchResponse(results=tuple(results))

    async def _search_provider(
        self, provider: str, query: SearchQuery
    ) -> ProviderGatewaySearchResult:
        normalized = provider.lower()
        if normalized not in self._providers:
            raise KeyError(f"Provider {provider!r} is not registered")
        track_provider = self._providers[normalized]
        policy = self._config.policy_for(normalized)
        attempts = max(1, policy.retry_max + 1)
        jitter_pct = self._jitter_pct(policy)
        attempt_counter = 0
        started = 0.0
        last_error: ProviderGatewayError | None = None

        async def _call() -> tuple[ProviderTrack, ...]:
            nonlocal attempt_counter, started
            attempt_counter += 1
            started = perf_counter()
            async with self._semaphore:
                result = await track_provider.search_tracks(query)
            return tuple(result)

        def _classify(exc: Exception) -> RetryDirective:
            nonlocal last_error
            error = self._normalise_error(track_provider, policy, exc)
            last_error = error
            self._log(track_provider.name, "error", attempt_counter, attempts, started, error)
            should_retry = self._should_retry(error) and attempt_counter < attempts
            return RetryDirective(retry=should_retry, error=error)

        error: Exception | None = None

        try:
            tracks = await with_retry(
                _call,
                attempts=attempts,
                base_ms=policy.backoff_base_ms,
                jitter_pct=jitter_pct,
                timeout_ms=policy.timeout_ms,
                classify_err=_classify,
            )
        except ProviderGatewayError as exc:
            error = exc
        except Exception as exc:  # pragma: no cover - defensive guard
            error = ProviderGatewayInternalError(track_provider.name, "unexpected error", cause=exc)
        else:
            self._log(track_provider.name, "success", attempt_counter, attempts, started)
            return ProviderGatewaySearchResult(
                provider=track_provider.name,
                tracks=tracks,
            )

        if isinstance(error, ProviderGatewayError):
            return ProviderGatewaySearchResult(
                provider=track_provider.name,
                tracks=tuple(),
                error=error,
            )

        if last_error is None:
            raise RuntimeError("Retry loop exited without error classification.")
        return ProviderGatewaySearchResult(
            provider=track_provider.name,
            tracks=tuple(),
            error=last_error,
        )

    @staticmethod
    def _jitter_pct(policy: ProviderRetryPolicy) -> int:
        value = max(0.0, policy.jitter_pct)
        if value <= 1:
            return int(round(value * 100))
        return int(round(value))

    def _normalise_error(
        self,
        provider: TrackProvider,
        policy: ProviderRetryPolicy,
        exc: Exception,
    ) -> ProviderGatewayError:
        name = provider.name
        if isinstance(exc, asyncio.TimeoutError):
            return ProviderGatewayTimeoutError(name, policy.timeout_ms, cause=exc)
        if isinstance(exc, ProviderTimeoutError):
            return ProviderGatewayTimeoutError(name, exc.timeout_ms, cause=exc)
        if isinstance(exc, ProviderValidationError):
            return ProviderGatewayValidationError(name, status_code=exc.status_code, cause=exc)
        if isinstance(exc, ProviderRateLimitedError):
            return ProviderGatewayRateLimitedError(
                name,
                retry_after_ms=exc.retry_after_ms,
                retry_after_header=exc.retry_after_header,
                status_code=exc.status_code,
                cause=exc,
            )
        if isinstance(exc, ProviderNotFoundError):
            return ProviderGatewayNotFoundError(name, status_code=exc.status_code, cause=exc)
        if isinstance(exc, ProviderDependencyError):
            return ProviderGatewayDependencyError(name, status_code=exc.status_code, cause=exc)
        if isinstance(exc, ProviderInternalError):
            return ProviderGatewayInternalError(name, str(exc), cause=exc)
        if isinstance(exc, ProviderError):
            return ProviderGatewayInternalError(name, str(exc), cause=exc)
        return ProviderGatewayInternalError(name, "unexpected error", cause=exc)

    @staticmethod
    def _should_retry(error: ProviderGatewayError) -> bool:
        return isinstance(
            error,
            (
                ProviderGatewayTimeoutError,
                ProviderGatewayRateLimitedError,
                ProviderGatewayDependencyError,
            ),
        )

    def _log(
        self,
        provider: str,
        status: str,
        attempt: int,
        attempts: int,
        started: float,
        error: ProviderGatewayError | None = None,
    ) -> None:
        duration_ms = int((perf_counter() - started) * 1000)
        meta: dict[str, object] = {"attempt": attempt, "max_attempts": attempts}
        payload: dict[str, object] = {
            "component": "provider_gateway",
            "dependency": provider,
            "operation": "search_tracks",
            "status": "ok" if status == "success" else "error",
            "duration_ms": duration_ms,
            "meta": meta,
        }
        if error is not None:
            meta["error"] = error.__class__.__name__
            if isinstance(error, ProviderGatewayRateLimitedError):
                meta["retry_after_ms"] = error.retry_after_ms
                if error.retry_after_header is not None:
                    meta["retry_after_header"] = error.retry_after_header
                if error.status_code is not None:
                    meta["status_code"] = error.status_code
            if (
                isinstance(
                    error,
                    (
                        ProviderGatewayDependencyError,
                        ProviderGatewayValidationError,
                        ProviderGatewayNotFoundError,
                    ),
                )
                and error.status_code is not None
            ):
                meta["status_code"] = error.status_code
            if isinstance(error, ProviderGatewayTimeoutError):
                meta["timeout_ms"] = error.timeout_ms
        log_event(logger, "api.dependency", **payload)


__all__ = [
    "ProviderGateway",
    "ProviderGatewayConfig",
    "ProviderGatewayDependencyError",
    "ProviderGatewayError",
    "ProviderGatewayInternalError",
    "ProviderGatewayNotFoundError",
    "ProviderGatewayRateLimitedError",
    "ProviderGatewayTimeoutError",
    "ProviderGatewayValidationError",
    "ProviderGatewaySearchResponse",
    "ProviderGatewaySearchResult",
    "ProviderRetryPolicy",
]
