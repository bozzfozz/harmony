from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import Download


def seed_downloads() -> dict[str, int]:
    with session_scope() as session:
        older = Download(
            filename="old.mp3",
            state="completed",
            progress=100.0,
            priority=2,
        )
        newer = Download(
            filename="new.mp3",
            state="queued",
            progress=0.0,
            priority=5,
        )
        failed = Download(
            filename="failed.mp3",
            state="failed",
            progress=0.0,
            priority=1,
        )
        session.add_all([older, newer, failed])
        session.flush()

        older.created_at = datetime.utcnow() - timedelta(days=2)
        older.updated_at = older.created_at
        session.add(older)
        return {"older": older.id, "newer": newer.id, "failed": failed.id}


def test_json_export_returns_full_payload(client) -> None:
    ids = seed_downloads()

    response = client.get("/downloads/export", params={"format": "json"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    payload = response.json()
    assert isinstance(payload, list)
    assert {entry["id"] for entry in payload} == set(ids.values())
    queued_entry = next(entry for entry in payload if entry["id"] == ids["newer"])
    assert queued_entry["priority"] == 5
    assert queued_entry["status"] == "pending"


def test_csv_export_contains_expected_header(client) -> None:
    seed_downloads()

    response = client.get("/downloads/export", params={"format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    body = response._body.decode("utf-8")
    rows = body.strip().splitlines()
    assert rows[0] == "id,filename,status,progress,username,created_at,updated_at"
    assert any("new.mp3" in row for row in rows[1:])


def test_status_filter_limits_export(client) -> None:
    ids = seed_downloads()

    response = client.get(
        "/downloads/export",
        params={"format": "json", "status": "failed"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert {entry["id"] for entry in payload} == {ids["failed"]}


def test_date_filters_apply_to_export(client) -> None:
    ids = seed_downloads()
    cutoff = datetime.utcnow() - timedelta(days=1)

    response = client.get(
        "/downloads/export",
        params={"format": "json", "from": cutoff.isoformat()},
    )
    assert response.status_code == 200
    payload = response.json()
    assert {entry["id"] for entry in payload} == {ids["newer"], ids["failed"]}


def test_invalid_format_returns_422(client) -> None:
    response = client.get("/downloads/export", params={"format": "xml"})
    assert response.status_code == 422


def test_invalid_date_returns_422(client) -> None:
    response = client.get("/downloads/export", params={"from": "invalid"})
    assert response.status_code == 422
