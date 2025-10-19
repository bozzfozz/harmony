from __future__ import annotations

from typing import Any

from app.core.transfers_api import TransfersApiError
from app.db import init_db, session_scope
from app.models import Download
from app.services.download_service import DownloadService


class _QueueStub:
    def __init__(self, responses: dict[int, dict[str, Any]]) -> None:
        self._responses = {int(key): dict(value) for key, value in responses.items()}
        self.calls: list[str] = []

    async def get_download_queue(self, transfer_id: int | str) -> dict[str, Any]:
        self.calls.append(str(transfer_id))
        payload = self._responses.get(int(transfer_id))
        return dict(payload) if payload is not None else {}


class _FailingQueueStub:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: list[str] = []

    async def get_download_queue(self, transfer_id: int | str) -> dict[str, Any]:
        self.calls.append(str(transfer_id))
        raise self._exc


def _make_service(session, transfers) -> DownloadService:
    async def runner(func):
        return func(session)

    return DownloadService(session=session, session_runner=runner, transfers=transfers)


def _create_download(session, **overrides: Any) -> Download:
    defaults: dict[str, Any] = {
        "filename": "track.flac",
        "state": "queued",
        "progress": 0.0,
        "priority": 0,
        "username": "tester",
    }
    defaults.update(overrides)

    download = Download(**defaults)
    session.add(download)
    session.commit()
    session.refresh(download)
    return download


def test_list_downloads_populates_live_queue_metadata() -> None:
    init_db()
    with session_scope() as session:
        active = _create_download(
            session,
            filename="active.flac",
            state="queued",
            priority=5,
        )
        completed = _create_download(
            session,
            filename="complete.flac",
            state="completed",
            progress=1.0,
        )

        transfers = _QueueStub({active.id: {"position": 2, "status": "waiting"}})
        service = _make_service(session, transfers)

        downloads = service.list_downloads(
            include_all=True,
            status_filter=None,
            limit=10,
            offset=0,
        )

        metadata = {record.id: getattr(record, "live_queue", None) for record in downloads}
        assert metadata[active.id] == {"position": 2, "status": "waiting"}
        assert metadata[completed.id] is None
        assert transfers.calls == [str(active.id)]


def test_list_downloads_handles_queue_errors() -> None:
    init_db()
    with session_scope() as session:
        active = _create_download(session, state="queued")

        transfers = _FailingQueueStub(TransfersApiError("boom"))
        service = _make_service(session, transfers)

        downloads = service.list_downloads(
            include_all=True,
            status_filter=None,
            limit=5,
            offset=0,
        )

        assert getattr(downloads[0], "live_queue", None) is None
        assert transfers.calls == [str(active.id)]


def test_get_download_includes_live_queue_metadata() -> None:
    init_db()
    with session_scope() as session:
        download = _create_download(session, state="running")

        transfers = _QueueStub({download.id: {"position": 1}})
        service = _make_service(session, transfers)

        record = service.get_download(download.id)

        assert getattr(record, "live_queue", None) == {"position": 1}
        assert transfers.calls == [str(download.id)]
