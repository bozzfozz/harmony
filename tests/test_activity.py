from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.utils.activity import record_activity


def test_activity_endpoint_returns_latest_entries(client) -> None:
    record_activity("sync", "completed", details={"runs": 1})
    record_activity("search", "completed", details={"query": "test"})

    response = client.get("/activity")
    assert response.status_code == 200

    payload = response.json()
    entries = payload["items"]
    assert payload["total_count"] == 2
    assert isinstance(entries, list)
    assert len(entries) == 2
    assert entries[0]["type"] == "search"
    assert entries[0]["status"] == "completed"
    assert entries[1]["type"] == "sync"


def test_activity_endpoint_limits_to_fifty_entries(client) -> None:
    for index in range(60):
        record_activity("download", "queued", details={"index": index})

    response = client.get("/activity")
    assert response.status_code == 200

    payload = response.json()
    entries = payload["items"]
    assert payload["total_count"] == 60
    assert len(entries) == 50
    assert entries[0]["details"]["index"] == 59
    assert entries[-1]["details"]["index"] == 10


def test_record_activity_serialises_timezone_aware_timestamp() -> None:
    aware_timestamp = datetime(2024, 5, 4, 12, 30, 45, tzinfo=timezone(timedelta(hours=2)))

    payload = record_activity("test", "completed", timestamp=aware_timestamp)

    timestamp = payload["timestamp"]
    assert timestamp == "2024-05-04T10:30:45Z"
    assert timestamp.endswith("Z")
    assert timestamp.count("Z") == 1


def test_record_activity_details_datetime_serialises_to_utc() -> None:
    aware_detail = datetime(2024, 1, 15, 9, 45, 30, tzinfo=timezone(timedelta(hours=-5)))

    payload = record_activity("sync", "completed", details={"finished_at": aware_detail})

    finished_at = payload["details"]["finished_at"]
    expected = aware_detail.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    assert finished_at == expected
    assert finished_at.endswith("Z")
    assert finished_at.count("Z") == 1
