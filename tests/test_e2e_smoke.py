from datetime import datetime
from typing import Any, Dict

from app.db import session_scope
from app.models import Download


def test_e2e_download_smoke(client) -> None:
    class ImmediateSyncWorker:
        def __init__(self) -> None:
            self.jobs: list[Dict[str, Any]] = []

        async def enqueue(self, job: Dict[str, Any]) -> None:
            self.jobs.append(job)
            now = datetime.utcnow()
            with session_scope() as session:
                for file_info in job.get("files", []):
                    identifier = file_info.get("download_id")
                    if identifier is None:
                        continue
                    download = session.get(Download, int(identifier))
                    if download is None:
                        continue
                    download.state = "completed"
                    download.progress = 100.0
                    download.updated_at = now

        async def stop(self) -> None:
            return None

    client.app.state.sync_worker = ImmediateSyncWorker()

    payload = {
        "username": "smoke-user",
        "files": [{"filename": "smoke.mp3"}],
    }

    response = client.post("/download", json=payload)
    assert response.status_code == 202

    downloads_response = client.get("/downloads", params={"all": "true"})
    assert downloads_response.status_code == 200
    downloads_payload = downloads_response.json()["downloads"]
    assert downloads_payload
    download_entry = downloads_payload[0]
    assert download_entry["status"] == "completed"
    assert download_entry["progress"] == 100.0
    assert download_entry["username"] == "smoke-user"

    activity_response = client.get("/activity")
    assert activity_response.status_code == 200
    activity_items = activity_response.json()["items"]
    assert any(item["type"] == "download" and item["status"] == "queued" for item in activity_items)
