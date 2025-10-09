from datetime import datetime, timedelta, timezone

from app.utils.activity import (
    activity_manager,
    record_worker_started,
    record_worker_stopped,
)
from app.utils.events import (
    WORKER_RESTARTED,
    WORKER_STALE,
    WORKER_STARTED,
    WORKER_STOPPED,
)
from app.utils.settings_store import write_setting
from app.utils.worker_health import (
    STALE_TIMEOUT_SECONDS,
    heartbeat_key,
    mark_worker_status,
)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def test_worker_start_records_activity(client) -> None:
    record_worker_started("sync")

    entries = activity_manager.list()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["type"] == "worker"
    assert entry["status"] == WORKER_STARTED
    assert entry["details"]["worker"] == "sync"
    assert "timestamp" in entry["details"]


def test_worker_stop_records_activity(client) -> None:
    record_worker_stopped("artwork")

    entries = activity_manager.list()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["type"] == "worker"
    assert entry["status"] == WORKER_STOPPED
    assert entry["details"]["worker"] == "artwork"


def test_worker_stale_event_emitted_on_health_check(client) -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    write_setting(heartbeat_key("matching"), _iso(past))
    mark_worker_status("matching", "running")

    response = client.get("/status")
    assert response.status_code == 200

    entries = activity_manager.list()
    assert len(entries) == 1
    entry = entries[0]
    details = entry["details"]
    assert entry["status"] == WORKER_STALE
    assert details["worker"] == "matching"
    assert details["last_seen"] == _iso(past)
    assert details["threshold_seconds"] == float(STALE_TIMEOUT_SECONDS)
    assert details["elapsed_seconds"] >= 120.0


def test_worker_restart_records_activity(client) -> None:
    record_worker_started("playlist")
    mark_worker_status("playlist", WORKER_STOPPED)

    record_worker_started("playlist")

    entries = activity_manager.list()
    assert len(entries) == 2
    latest = entries[0]
    previous = entries[1]

    assert previous["status"] == WORKER_STARTED
    assert latest["status"] == WORKER_RESTARTED
    assert latest["details"]["worker"] == "playlist"
    assert latest["details"].get("previous_status") == WORKER_STOPPED
