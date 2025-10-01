from __future__ import annotations

import asyncio

import pytest

from app.core.matching_engine import MusicMatchingEngine
from app.db import init_db, reset_engine_for_tests
from app.workers.matching_worker import MatchingWorker


@pytest.mark.asyncio
async def test_matching_worker_stop_allows_queue_join() -> None:
    reset_engine_for_tests()
    init_db()
    worker = MatchingWorker(MusicMatchingEngine())

    await worker.start()
    await worker.stop()

    await asyncio.wait_for(worker.queue.join(), timeout=1)
