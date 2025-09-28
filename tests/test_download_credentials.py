from sqlalchemy import delete

from app.db import session_scope
from app.models import ActivityEvent, Download, Setting
from app.utils.events import DOWNLOAD_BLOCKED


def test_download_endpoint_blocks_without_soulseek_credentials(client) -> None:
    with session_scope() as session:
        session.execute(delete(Setting).where(Setting.key == "SLSKD_URL"))
        session.commit()

    payload = {"username": "tester", "files": [{"filename": "Track.mp3"}]}

    response = client.post("/download", json=payload)

    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    error = body["error"]
    assert error["code"] == "DEPENDENCY_ERROR"
    assert error["message"] == "Download blocked"
    missing = set(error.get("meta", {}).get("missing", []))
    assert missing == {"soulseek"}

    with session_scope() as session:
        downloads = session.query(Download).all()
        assert downloads == []
        event = session.query(ActivityEvent).order_by(ActivityEvent.id.desc()).first()

    assert event is not None
    assert event.type == "download"
    assert event.status == DOWNLOAD_BLOCKED
