"""Retry and backoff helpers for Harmony services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import random
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryDirective:
    """Instruction returned from ``classify_err`` for ``with_retry``."""

    retry: bool
    delay_override_ms: int | None = None
    error: Exception | None = None


AsyncFactory = Callable[[], Awaitable[T]]
Classifier = Callable[[Exception], RetryDirective | bool]


def exp_backoff_delays(base_ms: int, max_attempts: int, jitter_pct: int) -> list[int]:
    """Return exponential backoff delays in milliseconds.

    ``jitter_pct`` influences the returned delay to account for jitter by
    increasing each delay by the configured percentage. The jitter application is
    deterministic so that the nominal delay can be inspected in tests; random
    jitter is applied when actually sleeping.
    """

    base = max(1, int(base_ms))
    attempts = max(0, int(max_attempts))
    pct = max(0, int(jitter_pct))
    delays: list[int] = []
    for index in range(attempts):
        delay = base * (2**index)
        if pct:
            jitter = int(delay * pct / 100)
            delay += jitter
        delays.append(delay)
    return delays


def _resolve_directive(result: RetryDirective | bool, error: Exception) -> RetryDirective:
    if isinstance(result, RetryDirective):
        resolved_error = result.error if result.error is not None else error
        return RetryDirective(
            retry=bool(result.retry),
            delay_override_ms=(
                max(0, int(result.delay_override_ms))
                if result.delay_override_ms is not None
                else None
            ),
            error=resolved_error,
        )
    if isinstance(result, bool):
        return RetryDirective(retry=result, error=error, delay_override_ms=None)
    msg = "classify_err must return a boolean or RetryDirective"
    raise TypeError(msg)


def _jitter_delay_ms(delay_ms: int, jitter_pct: int) -> float:
    delay = max(0, int(delay_ms))
    pct = max(0, int(jitter_pct))
    if delay <= 0 or pct <= 0:
        return float(delay)
    jitter = delay * pct / 100.0
    lower = max(0.0, delay - jitter)
    upper = delay + jitter
    return random.uniform(lower, upper)


async def with_retry(
    async_fn: AsyncFactory[T],
    *,
    attempts: int,
    base_ms: int,
    jitter_pct: int,
    timeout_ms: int | None,
    classify_err: Classifier,
) -> T:
    """Execute ``async_fn`` with retries, exponential backoff and jitter."""

    max_attempts = max(1, int(attempts))
    base = max(1, int(base_ms))
    timeout = int(timeout_ms) if timeout_ms is not None else None
    delays = exp_backoff_delays(base, max_attempts, 0)

    for attempt in range(1, max_attempts + 1):
        try:
            call = async_fn()
            if timeout is not None and timeout > 0:
                return await asyncio.wait_for(call, timeout / 1000.0)
            return await call
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - exercised via tests
            directive = _resolve_directive(classify_err(exc), exc)
            should_retry = directive.retry and attempt < max_attempts
            if not should_retry:
                raise directive.error from exc if directive.error is not exc else exc

            delay_ms = directive.delay_override_ms
            if delay_ms is None:
                delay_ms = delays[attempt - 1]
            jittered_ms = _jitter_delay_ms(delay_ms, jitter_pct)
            if jittered_ms > 0:
                await asyncio.sleep(jittered_ms / 1000.0)
    # ``for`` loop must return or raise before reaching here.
    raise RuntimeError("Retry loop exited unexpectedly")


__all__ = [
    "RetryDirective",
    "exp_backoff_delays",
    "with_retry",
]
