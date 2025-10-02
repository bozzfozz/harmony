"""Concurrency primitives shared across Harmony services."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager

__all__ = ["BoundedPools", "acquire_pair"]


class BoundedPools:
    """Manage a global semaphore and per-pool limits."""

    def __init__(
        self,
        *,
        global_limit: int,
        pool_limits: Mapping[str, int] | None = None,
    ) -> None:
        limit = max(1, int(global_limit))
        self._global_limit = limit
        self._global = asyncio.Semaphore(limit)
        base: dict[str, int] = {}
        if pool_limits:
            for name, value in pool_limits.items():
                key = str(name)
                base[key] = max(1, int(value))
        self._pool_limits = base
        self._pools: dict[str, asyncio.Semaphore] = {}

    @property
    def global_limit(self) -> int:
        return self._global_limit

    @property
    def global_semaphore(self) -> asyncio.Semaphore:
        return self._global

    def limit_for(self, name: str) -> int:
        key = str(name)
        return self._pool_limits.get(key, self._global_limit)

    def semaphore_for(self, name: str) -> asyncio.Semaphore:
        key = str(name)
        semaphore = self._pools.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.limit_for(key))
            self._pools[key] = semaphore
        return semaphore

    @asynccontextmanager
    async def acquire(self, name: str):
        semaphore = self.semaphore_for(name)
        async with acquire_pair(self._global, semaphore):
            yield


@asynccontextmanager
async def acquire_pair(global_sem: asyncio.Semaphore, pool_sem: asyncio.Semaphore):
    """Acquire both semaphores in order, releasing safely on exit."""

    async with global_sem:
        async with pool_sem:
            yield
