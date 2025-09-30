"""Gateway orchestrating provider calls with shared policies."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Sequence

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


logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class ProviderRetryPolicy:
    """Retry and timeout behaviour for a provider."""

    timeout_ms: int
    retry_max: int
    backoff_base_ms: int
    jitter_pct: float


@dataclass(slots=True, frozen=True)
class ProviderGatewayConfig:
    """Runtime configuration for the provider gateway."""

    max_concurrency: int
    default_policy: ProviderRetryPolicy
    provider_policies: Mapping[str, ProviderRetryPolicy]

    def policy_for(self, provider: str) -> ProviderRetryPolicy:
        return self.provider_policies.get(provider, self.default_policy)


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
    def __init__(self, provider: str, *, status_code: int | None, cause: Exception | None = None) -> None:
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
    def __init__(self, provider: str, *, status_code: int | None, cause: Exception | None = None) -> None:
        super().__init__(provider, f"{provider} returned no results", cause=cause)
        self.status_code = status_code


class ProviderGatewayDependencyError(ProviderGatewayError):
    def __init__(self, provider: str, *, status_code: int | None, cause: Exception | None = None) -> None:
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

        tasks = [asyncio.create_task(_run(provider)) for provider in providers]
        results = await asyncio.gather(*tasks)
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
        error: ProviderGatewayError | None = None

        for attempt in range(1, attempts + 1):
            started = perf_counter()
            error = None
            try:
                async with self._semaphore:
                    result = await asyncio.wait_for(
                        track_provider.search_tracks(query),
                        timeout=policy.timeout_ms / 1000,
                    )
                tracks = tuple(result)
                self._log(track_provider.name, "success", attempt, attempts, started)
                return ProviderGatewaySearchResult(
                    provider=track_provider.name,
                    tracks=tracks,
                )
            except asyncio.TimeoutError as exc:
                error = ProviderGatewayTimeoutError(track_provider.name, policy.timeout_ms, cause=exc)
            except ProviderTimeoutError as exc:
                error = ProviderGatewayTimeoutError(track_provider.name, exc.timeout_ms, cause=exc)
            except ProviderValidationError as exc:
                error = ProviderGatewayValidationError(
                    track_provider.name,
                    status_code=exc.status_code,
                    cause=exc,
                )
            except ProviderRateLimitedError as exc:
                error = ProviderGatewayRateLimitedError(
                    track_provider.name,
                    retry_after_ms=exc.retry_after_ms,
                    retry_after_header=exc.retry_after_header,
                    status_code=exc.status_code,
                    cause=exc,
                )
            except ProviderNotFoundError as exc:
                error = ProviderGatewayNotFoundError(
                    track_provider.name,
                    status_code=exc.status_code,
                    cause=exc,
                )
            except ProviderDependencyError as exc:
                error = ProviderGatewayDependencyError(
                    track_provider.name,
                    status_code=exc.status_code,
                    cause=exc,
                )
            except ProviderInternalError as exc:
                error = ProviderGatewayInternalError(track_provider.name, str(exc))
                error.cause = exc
            except ProviderError as exc:
                error = ProviderGatewayInternalError(track_provider.name, str(exc))
                error.cause = exc
            except Exception as exc:  # pragma: no cover - defensive guard
                error = ProviderGatewayInternalError(track_provider.name, "unexpected error")
                error.cause = exc

            assert error is not None  # for type checkers
            self._log(track_provider.name, "error", attempt, attempts, started, error)

            should_retry = self._should_retry(error) and attempt < attempts
            if not should_retry:
                break

            backoff_seconds = self._backoff_seconds(policy, attempt)
            if backoff_seconds > 0:
                await asyncio.sleep(backoff_seconds)

        assert error is not None
        return ProviderGatewaySearchResult(
            provider=track_provider.name,
            tracks=tuple(),
            error=error,
        )

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

    @staticmethod
    def _backoff_seconds(policy: ProviderRetryPolicy, attempt: int) -> float:
        exponent = max(0, attempt - 1)
        base_ms = policy.backoff_base_ms * (2**exponent)
        jitter_range = base_ms * policy.jitter_pct
        if jitter_range:
            delay_ms = base_ms + random.uniform(-jitter_range, jitter_range)
        else:
            delay_ms = base_ms
        return max(0.0, delay_ms / 1000)

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
        extra: dict[str, object] = {
            "event": "api.dependency",
            "provider": provider,
            "operation": "search_tracks",
            "status": status,
            "attempt": attempt,
            "max_attempts": attempts,
            "duration_ms": duration_ms,
        }
        if error is not None:
            extra["error"] = error.__class__.__name__
            if isinstance(error, ProviderGatewayRateLimitedError):
                extra["retry_after_ms"] = error.retry_after_ms
            if isinstance(error, ProviderGatewayDependencyError):
                extra["status_code"] = error.status_code
            if isinstance(error, ProviderGatewayValidationError):
                extra["status_code"] = error.status_code
            if isinstance(error, ProviderGatewayNotFoundError):
                extra["status_code"] = error.status_code
            if isinstance(error, ProviderGatewayTimeoutError):
                extra["timeout_ms"] = error.timeout_ms
        log = logger.info if status == "success" else logger.warning
        log("provider call", extra=extra)


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

