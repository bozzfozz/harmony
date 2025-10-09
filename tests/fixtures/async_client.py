"""Shared HTTPX AsyncClient fixture with configurable deadline helpers."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Iterator

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from tests.simple_client import SimpleTestClient

DEFAULT_ASYNC_DEADLINE_S = 0.75


class DeadlineHelper:
    """Provide helper utilities for tracking async execution deadlines."""

    def __init__(
        self,
        *,
        default: float = DEFAULT_ASYNC_DEADLINE_S,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._default = default
        self._clock = clock

    @property
    def default(self) -> float:
        return self._default

    @asynccontextmanager
    async def limit(
        self, seconds: float | None = None
    ) -> Iterator[Callable[[], float]]:
        """Enforce that async operations finish within ``seconds``."""

        budget = self._default if seconds is None else seconds
        start = self._clock()
        with anyio.fail_after(budget):
            yield lambda: self._clock() - start


@dataclass
class AsyncDeadlineClient:
    """Container bundling an AsyncClient with deadline helpers."""

    client: AsyncClient
    deadline: DeadlineHelper

    @asynccontextmanager
    async def within(
        self, seconds: float | None = None
    ) -> AsyncIterator[tuple[AsyncClient, Callable[[], float]]]:
        async with self.deadline.limit(seconds) as elapsed:
            yield self.client, elapsed


@pytest.fixture
async def async_client_with_deadline(
    client: SimpleTestClient,
) -> AsyncIterator[AsyncDeadlineClient]:
    """Yield an AsyncClient ready for API tests with a shared deadline helper."""

    deadline = DeadlineHelper()
    transport = ASGITransport(app=client.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as http_client:
        yield AsyncDeadlineClient(client=http_client, deadline=deadline)


@pytest.fixture
def anyio_backend() -> str:
    """Force async tests to run against the asyncio backend."""

    return "asyncio"
