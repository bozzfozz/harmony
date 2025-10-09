from __future__ import annotations

from typing import List


def _extract_history_for_key(history: List[dict], key: str) -> List[dict]:
    return [entry for entry in history if entry["key"] == key]


def test_settings_history_tracking(client) -> None:
    response = client.post("/settings", json={"key": "theme", "value": "light"})
    assert response.status_code == 200

    response = client.post("/settings", json={"key": "theme", "value": "dark"})
    assert response.status_code == 200

    response = client.post(
        "/settings", json={"key": "notifications", "value": "enabled"}
    )
    assert response.status_code == 200

    history_response = client.get("/settings/history")
    assert history_response.status_code == 200
    payload = history_response.json()

    assert "history" in payload
    history_entries = payload["history"]
    assert len(history_entries) >= 3

    theme_history = _extract_history_for_key(history_entries, "theme")
    assert len(theme_history) == 2

    first_entry, second_entry = theme_history[0], theme_history[1]
    assert first_entry["new_value"] == "dark"
    assert first_entry["old_value"] == "light"
    assert second_entry["new_value"] == "light"
    assert second_entry["old_value"] is None
    assert first_entry["changed_at"] >= second_entry["changed_at"]
