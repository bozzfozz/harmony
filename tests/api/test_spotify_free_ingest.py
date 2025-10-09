from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import anyio
from httpx import ASGITransport, AsyncClient, Response
import pytest

from app.db import SessionCallable, session_scope
from app.dependencies import SessionRunner, get_session_runner
from app.models import IngestItem, IngestItemState, IngestJob, IngestJobState
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient

pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
async def async_client(client: SimpleTestClient) -> AsyncClient:
    transport = ASGITransport(app=client.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as http_client:
        yield http_client


def _slow_runner(delay: float, runner: SessionRunner) -> SessionRunner:
    async def _wrapper(func: SessionCallable[Any]) -> Any:
        def _delayed(session):
            time.sleep(delay)
            return func(session)

        return await runner(_delayed)

    return _wrapper


async def test_free_ingest_pipeline_uses_async_db_executor(
    client: SimpleTestClient, async_client: AsyncClient
) -> None:
    delay = 0.25
    original_runner = get_session_runner()
    client.app.dependency_overrides[get_session_runner] = lambda: _slow_runner(
        delay, original_runner
    )

    ticker_count = 0

    async def ticker() -> None:
        nonlocal ticker_count
        try:
            while True:
                await asyncio.sleep(0.05)
                ticker_count += 1
        except asyncio.CancelledError:
            pass

    ticker_task = asyncio.create_task(ticker())
    response: Response | None = None
    elapsed = 0.0
    try:
        start = time.perf_counter()
        with anyio.fail_after(3.0):
            response = await async_client.post(
                api_path("/spotify/import/free"),
                json={"tracks": ["Soulseek Artist - Test Song"]},
            )
        elapsed = time.perf_counter() - start
    finally:
        ticker_task.cancel()
        with contextlib.suppress(BaseException):
            await ticker_task
        client.app.dependency_overrides.pop(get_session_runner, None)

    assert response is not None
    assert response.status_code == 202
    assert elapsed >= delay
    assert ticker_count > 0

    payload = response.json()
    job_id = payload["job_id"]
    assert isinstance(job_id, str) and job_id

    with session_scope() as session:
        job = session.get(IngestJob, job_id)
        assert job is not None
        assert job.state == IngestJobState.COMPLETED.value
        items = (
            session.query(IngestItem)
            .filter(IngestItem.job_id == job_id, IngestItem.source_type != "LINK")
            .all()
        )
        assert items, "expected at least one track item"
        assert all(item.state == IngestItemState.QUEUED.value for item in items)
