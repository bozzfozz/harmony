import asyncio

import pytest

from app.utils.concurrency import BoundedPools, acquire_pair


@pytest.mark.asyncio
async def test_bounded_pools_enforces_pool_limit():
    pools = BoundedPools(global_limit=2, pool_limits={"sync": 1})
    entered: list[str] = []
    release = asyncio.Event()

    async def first():
        async with pools.acquire("sync"):
            entered.append("first")
            await release.wait()

    async def second():
        async with pools.acquire("sync"):
            entered.append("second")

    task_one = asyncio.create_task(first())
    await asyncio.sleep(0)
    task_two = asyncio.create_task(second())
    await asyncio.sleep(0)

    assert entered == ["first"]

    release.set()
    await asyncio.sleep(0)
    await task_two
    await task_one

    assert entered == ["first", "second"]


@pytest.mark.asyncio
async def test_acquire_pair_acquires_both():
    global_sem = asyncio.Semaphore(1)
    pool_sem = asyncio.Semaphore(1)
    acquired: list[str] = []

    async def worker():
        async with acquire_pair(global_sem, pool_sem):
            acquired.append("entered")

    await asyncio.gather(worker(), worker())
    assert acquired == ["entered", "entered"]
