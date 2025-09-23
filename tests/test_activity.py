from __future__ import annotations

from app.utils.activity import record_activity


def test_activity_endpoint_returns_latest_entries(client) -> None:
    record_activity("sync", "completed", details={"runs": 1})
    record_activity("search", "completed", details={"query": "test"})

    response = client.get("/api/activity")
    assert response.status_code == 200

    entries = response.json()
    assert isinstance(entries, list)
    assert len(entries) == 2
    assert entries[0]["type"] == "search"
    assert entries[0]["status"] == "completed"
    assert entries[1]["type"] == "sync"


def test_activity_endpoint_limits_to_fifty_entries(client) -> None:
    for index in range(60):
        record_activity("download", "queued", details={"index": index})

    response = client.get("/api/activity")
    assert response.status_code == 200

    entries = response.json()
    assert len(entries) == 50
    assert entries[0]["details"]["index"] == 59
    assert entries[-1]["details"]["index"] == 10
