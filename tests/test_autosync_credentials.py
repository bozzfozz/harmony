import pytest
from sqlalchemy import delete

from app.db import session_scope
from app.models import ActivityEvent, Setting
from app.utils.events import AUTOSYNC_BLOCKED
from app.workers.auto_sync_worker import AutoSyncWorker


class DummyBeetsClient:
    def import_file(self, path: str, quiet: bool = True) -> str:  # pragma: no cover - defensive
        return path


@pytest.mark.asyncio
async def test_autosync_worker_blocks_when_credentials_missing(client) -> None:
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

    app = client.app
    worker = AutoSyncWorker(
        spotify_client=app.state.spotify_stub,
        plex_client=app.state.plex_stub,
        soulseek_client=app.state.soulseek_stub,
        beets_client=DummyBeetsClient(),
    )

    await worker.run_once(source="manual")

    with session_scope() as session:
        event = (
            session.query(ActivityEvent)
            .order_by(ActivityEvent.id.desc())
            .first()
        )

    assert event is not None
    assert event.type == "autosync"
    assert event.status == AUTOSYNC_BLOCKED
    missing = event.details.get("missing", {}) if event.details else {}
    assert set(missing) == {"spotify", "plex", "soulseek"}
