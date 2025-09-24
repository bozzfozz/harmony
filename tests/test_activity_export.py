from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO

from app.utils.activity import record_activity


def _create_events() -> None:
    base_time = datetime(2024, 3, 18, 12, 0, 0)
    record_activity(
        "sync",
        "completed",
        timestamp=base_time,
        details={"runs": 2},
    )
    record_activity(
        "download",
        "failed",
        timestamp=base_time - timedelta(minutes=5),
        details={"id": 42},
    )


def test_activity_export_json(client) -> None:
    _create_events()

    response = client.get("/api/activity/export", params={"format": "json"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert payload[0]["type"] == "sync"
    assert payload[0]["status"] == "completed"
    assert payload[1]["type"] == "download"
    assert payload[1]["status"] == "failed"


def test_activity_export_csv(client) -> None:
    _create_events()

    response = client.get("/api/activity/export", params={"format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    csv_text = response._body.decode("utf-8")
    reader = csv.DictReader(StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 2
    assert reader.fieldnames == ["id", "timestamp", "type", "status", "details"]
    assert rows[0]["type"] == "sync"
    assert rows[0]["status"] == "completed"
    assert rows[0]["details"] == "{\"runs\":2}"


def test_activity_export_filters(client) -> None:
    _create_events()
    record_activity("sync", "failed")

    response = client.get(
        "/api/activity/export",
        params={"format": "json", "type": "download", "status": "failed"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["type"] == "download"
    assert payload[0]["status"] == "failed"


def test_activity_export_invalid_format(client) -> None:
    response = client.get("/api/activity/export", params={"format": "xml"})
    assert response.status_code == 422


def test_activity_export_invalid_range(client) -> None:
    response = client.get(
        "/api/activity/export",
        params={"from": "2024-03-19T12:00:00", "to": "2024-03-18T12:00:00"},
    )
    assert response.status_code == 422
