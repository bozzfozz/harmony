from __future__ import annotations

import asyncio

from app.workers.scan_worker import ScanWorker


def test_metadata_update_lifecycle(client) -> None:
    response = client.post("/api/metadata/update")
    assert response.status_code == 202

    client._loop.run_until_complete(asyncio.sleep(0.05))

    status_response = client.get("/api/metadata/status")
    assert status_response.status_code == 200
    state = status_response.json()
    assert state["status"] in {"running", "completed"}

    client._loop.run_until_complete(asyncio.sleep(0.05))
    final_state = client.get("/api/metadata/status").json()
    assert final_state["status"] == "completed"


def test_metadata_update_prevents_parallel_runs(monkeypatch, client) -> None:
    async def slow_run_once(self) -> None:  # type: ignore[override]
        await asyncio.sleep(0.1)

    monkeypatch.setattr(ScanWorker, "run_once", slow_run_once, raising=False)

    first = client.post("/api/metadata/update")
    assert first.status_code == 202

    second = client.post("/api/metadata/update")
    assert second.status_code == 409

    client._loop.run_until_complete(asyncio.sleep(0.12))
    finished_state = client.get("/api/metadata/status").json()
    assert finished_state["status"] in {"completed", "stopped"}


def test_metadata_update_stop(monkeypatch, client) -> None:
    async def slow_run_once(self) -> None:  # type: ignore[override]
        await asyncio.sleep(0.1)

    monkeypatch.setattr(ScanWorker, "run_once", slow_run_once, raising=False)

    start_response = client.post("/api/metadata/update")
    assert start_response.status_code == 202

    stop_response = client.post("/api/metadata/stop")
    assert stop_response.status_code == 202
    stop_state = stop_response.json()["state"]
    assert stop_state["status"] == "stopping"

    client._loop.run_until_complete(asyncio.sleep(0.12))
    final_state = client.get("/api/metadata/status").json()
    assert final_state["status"] == "stopped"
