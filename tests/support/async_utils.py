"""Asynchronous utilities used exclusively by the test-suite."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


Predicate = Callable[[], Awaitable[bool] | bool]
T = TypeVar("T")


async def wait_for_condition(
    predicate: Predicate,
    *,
    timeout: float = 1.0,
    interval: float = 0.01,
) -> bool:
    """Poll *predicate* until it evaluates to ``True`` or *timeout* expires.

    The predicate can be synchronous or asynchronous.  ``False`` is returned when
    the timeout is reached without the predicate evaluating to ``True``.
    """

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result  # type: ignore[assignment]
        if result:
            return True
        if asyncio.get_event_loop().time() >= deadline:
            return False
        await asyncio.sleep(interval)


async def cancel_and_await(task: asyncio.Task[T], *, timeout: float = 0.5) -> None:
    """Cancel *task* and wait for it to finish, swallowing ``CancelledError``."""

    if task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        # Last resort best-effort cancellation.
        task.cancel()


async def wait_for_event(event: asyncio.Event, *, timeout: float = 1.0) -> bool:
    """Await ``asyncio.Event`` *event* with a bounded timeout."""

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    return True
