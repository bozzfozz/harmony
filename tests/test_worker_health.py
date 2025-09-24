from datetime import datetime, timedelta, timezone

from app.utils.settings_store import read_setting, write_setting
from app.utils.worker_health import (
    heartbeat_key,
    mark_worker_status,
    record_worker_heartbeat,
    status_key,
)


def test_worker_heartbeat_persists_setting(client) -> None:
    worker = client.app.state.sync_worker
    worker._record_heartbeat()

    stored = read_setting(heartbeat_key("sync"))
    assert stored is not None


def test_status_endpoint_reports_worker_health(client) -> None:
    record_worker_heartbeat("sync")
    record_worker_heartbeat("matching")
    mark_worker_status("scan", "running")

    response = client.get("/status")
    assert response.status_code == 200

    workers = response.json()["workers"]

    sync_info = workers["sync"]
    assert sync_info["status"] == "running"
    assert sync_info["queue_size"] == 0

    matching_info = workers["matching"]
    assert matching_info["status"] == "running"
    assert matching_info["queue_size"] == 0

    scan_info = workers["scan"]
    assert scan_info["queue_size"] == "n/a"


def test_worker_stop_sets_status_stopped(client) -> None:
    record_worker_heartbeat("matching")
    mark_worker_status("matching", "stopped")

    response = client.get("/status")
    assert response.status_code == 200

    assert response.json()["workers"]["matching"]["status"] == "stopped"


def test_worker_without_recent_heartbeat_is_stale(client) -> None:
    old_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    write_setting(heartbeat_key("sync"), old_timestamp)
    write_setting(status_key("sync"), "running")

    response = client.get("/status")
    assert response.status_code == 200

    assert response.json()["workers"]["sync"]["status"] == "stale"
