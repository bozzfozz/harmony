from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import ActivityEvent
from app.utils import activity_manager, record_activity


def test_activity_history_paging_and_total_count(client) -> None:
    activity_manager.clear()
    for index in range(5):
        record_activity("download", "queued", details={"index": index})

    first_page = client.get("/activity", params={"limit": 2, "offset": 0})
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["total_count"] == 5
    assert [entry["details"]["index"] for entry in payload["items"]] == [4, 3]

    second_page = client.get("/activity", params={"limit": 2, "offset": 2})
    assert second_page.status_code == 200
    payload_next = second_page.json()
    assert payload_next["total_count"] == 5
    assert [entry["details"]["index"] for entry in payload_next["items"]] == [2, 1]

    last_page = client.get("/activity", params={"limit": 2, "offset": 4})
    assert last_page.status_code == 200
    payload_last = last_page.json()
    assert payload_last["total_count"] == 5
    assert [entry["details"]["index"] for entry in payload_last["items"]] == [0]


def test_activity_history_filtering(client) -> None:
    activity_manager.clear()
    record_activity("sync", "ok")
    record_activity("download", "failed")
    record_activity("search", "failed")
    record_activity("download", "ok")

    downloads = client.get("/activity", params={"type": "download"})
    assert downloads.status_code == 200
    download_items = downloads.json()["items"]
    assert len(download_items) == 2
    assert all(entry["type"] == "download" for entry in download_items)

    failed = client.get("/activity", params={"status": "failed"})
    assert failed.status_code == 200
    failed_items = failed.json()["items"]
    assert len(failed_items) == 2
    assert all(entry["status"] == "failed" for entry in failed_items)

    failed_downloads = client.get(
        "/activity",
        params={"type": "download", "status": "failed"},
    )
    assert failed_downloads.status_code == 200
    combination = failed_downloads.json()["items"]
    assert len(combination) == 1
    assert combination[0]["type"] == "download"
    assert combination[0]["status"] == "failed"


def test_activity_history_persists_after_cache_clear(client) -> None:
    activity_manager.clear()
    record_activity("metadata", "partial", details={"batch": 1})

    # Simulate application restart by clearing the in-memory cache only
    activity_manager.clear()

    response = client.get("/activity")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["items"][0]["type"] == "metadata"
    assert payload["items"][0]["status"] == "partial"


def test_activity_total_matches_inserted_rows(client) -> None:
    activity_manager.clear()
    for index in range(23):
        record_activity("job", "done", details={"index": index})

    response = client.get("/activity", params={"limit": 5, "offset": 10})
    assert response.status_code == 200

    payload = response.json()
    assert payload["total_count"] == 23
    assert [entry["details"]["index"] for entry in payload["items"]] == [12, 11, 10, 9, 8]


def test_activity_order_is_desc_by_created_at_then_id(client) -> None:
    activity_manager.clear()
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    for index in range(3):
        record_activity(
            "sorted",
            "ok",
            timestamp=base_time + timedelta(minutes=index),
            details={"index": index},
        )
    # Insert an entry with an older timestamp after newer ones to ensure ordering
    record_activity(
        "sorted",
        "ok",
        timestamp=base_time - timedelta(minutes=5),
        details={"index": "older"},
    )
    # Create two entries with identical timestamps to validate ID tiebreaker
    record_activity(
        "sorted",
        "ok",
        timestamp=base_time + timedelta(minutes=2),
        details={"index": "tie_a"},
    )
    record_activity(
        "sorted",
        "ok",
        timestamp=base_time + timedelta(minutes=2),
        details={"index": "tie_b"},
    )

    response = client.get("/activity", params={"type": "sorted"})
    assert response.status_code == 200

    items = response.json()["items"]
    timestamps = [item["timestamp"] for item in items]
    assert timestamps == sorted(timestamps, reverse=True)
    returned_indices = [item["details"]["index"] for item in items]
    assert returned_indices[:3] == ["tie_b", "tie_a", 2]
    assert returned_indices[-1] == "older"


def test_activity_refresh_after_bulk_insert(client) -> None:
    activity_manager.clear()
    for index in range(2):
        record_activity("seed", "ok", details={"index": index})

    first_response = client.get("/activity")
    assert first_response.status_code == 200
    assert first_response.json()["total_count"] == 2

    now = datetime.utcnow()
    with session_scope() as session:
        session.bulk_save_objects(
            [
                ActivityEvent(
                    type="seed",
                    status="ok",
                    timestamp=now + timedelta(minutes=offset),
                    details={"index": f"bulk-{offset}"},
                )
                for offset in range(3)
            ]
        )

    # Refresh in-memory caches after the bulk write and ensure pagination cache is invalidated
    activity_manager.refresh_cache()

    refreshed = client.get("/activity")
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["total_count"] == 5
    returned_indices = [entry["details"]["index"] for entry in payload["items"][:3]]
    assert returned_indices == ["bulk-2", "bulk-1", "bulk-0"]
