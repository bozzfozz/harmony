"""Time helpers with monotonic clocks and jittered sleep."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import random
import time as _time

__all__ = ["now_utc", "monotonic_ms", "sleep_jitter_ms"]


def now_utc() -> datetime:
    """Return the current UTC time with timezone information."""

    return datetime.now(UTC)


def monotonic_ms() -> int:
    """Return a monotonic timestamp in milliseconds."""

    try:
        return _time.monotonic_ns() // 1_000_000
    except AttributeError:  # pragma: no cover - Python < 3.7 fallback
        return int(_time.monotonic() * 1000)


async def sleep_jitter_ms(ms: int, jitter_pct: int) -> float:
    """Sleep for ``ms`` milliseconds, applying +/- jitter percentage."""

    delay_ms = max(0, int(ms))
    pct = max(0, int(jitter_pct))
    actual_ms = float(delay_ms)
    if delay_ms > 0 and pct > 0:
        jitter = delay_ms * pct / 100.0
        lower = max(0.0, delay_ms - jitter)
        upper = delay_ms + jitter
        actual_ms = random.uniform(lower, upper)
    seconds = actual_ms / 1000.0
    if seconds > 0:
        await asyncio.sleep(seconds)
    else:  # pragma: no cover - zero path
        await asyncio.sleep(0)
    return seconds
