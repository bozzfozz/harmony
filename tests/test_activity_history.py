from __future__ import annotations

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
