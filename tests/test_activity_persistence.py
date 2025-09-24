from __future__ import annotations

from app.db import session_scope
from app.models import ActivityEvent
from app.utils.activity import activity_manager, record_activity


def test_activity_events_are_persisted_in_db(client) -> None:
    record_activity("sync", "completed", details={"runs": 1})

    with session_scope() as session:
        stored = session.query(ActivityEvent).order_by(ActivityEvent.id.desc()).first()

    assert stored is not None
    assert stored.type == "sync"
    assert stored.status == "completed"
    assert stored.details == {"runs": 1}


def test_activity_cache_can_reload_from_database(client) -> None:
    record_activity("matching", "batch_saved", details={"count": 5})

    activity_manager.clear()
    activity_manager.refresh_cache()

    entries = activity_manager.list()
    assert entries
    assert entries[0]["type"] == "matching"
    assert entries[0]["details"]["count"] == 5


def test_activity_endpoint_supports_paging(client) -> None:
    for index in range(30):
        record_activity("download", "queued", details={"index": index})

    response = client.get("/api/activity", params={"limit": 10, "offset": 5})
    assert response.status_code == 200

    payload = response.json()
    entries = payload["items"]
    assert payload["total_count"] == 30
    assert len(entries) == 10

    returned_indices = [entry["details"]["index"] for entry in entries]
    expected_indices = list(range(29 - 5, 29 - 5 - 10, -1))
    assert returned_indices == expected_indices


def test_activity_accepts_flexible_types(client) -> None:
    record_activity("autosync", "started", details={"source": "playlist"})

    response = client.get("/api/activity")
    assert response.status_code == 200

    payload = response.json()
    entries = payload["items"]
    assert payload["total_count"] >= 1
    assert entries
    assert entries[0]["type"] == "autosync"
    assert entries[0]["details"]["source"] == "playlist"
