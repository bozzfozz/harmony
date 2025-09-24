from __future__ import annotations

from sqlalchemy import select

from app.core.config import DEFAULT_SETTINGS
from app.db import session_scope
from app.models import Setting


def test_startup_populates_missing_defaults(client) -> None:
    with session_scope() as session:
        stored_settings = session.execute(select(Setting)).scalars().all()
    keys = {setting.key for setting in stored_settings}
    for key, value in DEFAULT_SETTINGS.items():
        assert key in keys
        stored = next(item for item in stored_settings if item.key == key)
        assert stored.value == value


def test_get_settings_returns_defaults(client) -> None:
    response = client.get("/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "settings" in payload
    settings = payload["settings"]
    for key, value in DEFAULT_SETTINGS.items():
        assert settings.get(key) == value


def test_post_settings_overrides_defaults(client) -> None:
    response = client.post(
        "/settings",
        json={"key": "sync_worker_concurrency", "value": "4"},
    )
    assert response.status_code == 200
    payload = response.json()
    settings = payload["settings"]
    assert settings["sync_worker_concurrency"] == "4"


def test_history_tracks_actual_changes(client) -> None:
    initial_history = client.get("/settings/history")
    assert initial_history.status_code == 200
    assert initial_history.json()["history"] == []

    response = client.post(
        "/settings",
        json={"key": "matching_worker_batch_size", "value": "8"},
    )
    assert response.status_code == 200

    history_response = client.get("/settings/history")
    assert history_response.status_code == 200
    history_entries = history_response.json()["history"]
    assert len(history_entries) == 1
    entry = history_entries[0]
    assert entry["key"] == "matching_worker_batch_size"
    assert entry["old_value"] == DEFAULT_SETTINGS["matching_worker_batch_size"]
    assert entry["new_value"] == "8"
