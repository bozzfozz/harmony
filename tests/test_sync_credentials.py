from sqlalchemy import delete

from app.db import session_scope
from app.models import ActivityEvent, Setting
from app.utils.events import SYNC_BLOCKED


def test_manual_sync_blocks_without_credentials(client) -> None:
    with session_scope() as session:
        session.execute(
            delete(Setting).where(
                Setting.key.in_(
                    [
                        "SPOTIFY_CLIENT_ID",
                        "SPOTIFY_CLIENT_SECRET",
                        "SPOTIFY_REDIRECT_URI",
                        "PLEX_BASE_URL",
                        "PLEX_TOKEN",
                        "SLSKD_URL",
                    ]
                )
            )
        )
        session.commit()

    response = client.post("/api/sync")

    assert response.status_code == 503
    payload = response.json()
    detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
    assert detail.get("message") == "Sync blocked"
    missing = detail.get("missing", {})
    assert set(missing) == {"spotify", "plex", "soulseek"}

    with session_scope() as session:
        event = (
            session.query(ActivityEvent)
            .order_by(ActivityEvent.id.desc())
            .first()
        )

    assert event is not None
    assert event.type == "sync"
    assert event.status == SYNC_BLOCKED
