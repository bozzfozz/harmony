"""Integration tests for the Soulseek router.

The test suite covers both synchronous download workflows (legacy tests) and
new asynchronous checks ensuring the upload endpoints return the expected JSON
payloads and translate `SoulseekClientError` instances into appropriate HTTP
exceptions (defaulting to 502). Success and failure paths for cancel, detail,
listing, and cleanup operations are exercised via mocked `SoulseekClient`
instances.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import importlib.util
from pathlib import Path
from uuid import uuid4
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from unittest.mock import AsyncMock, Mock

from app.config import load_config
from app.db import init_db, session_scope
from app.dependencies import get_app_config, get_db, get_soulseek_client
from app.models import DiscographyJob, Download
from app.core.soulseek_client import SoulseekClient, SoulseekClientError
from app.utils.path_safety import allowed_download_roots

_SOULSEEK_MODULE_SPEC = importlib.util.spec_from_file_location(
    "app.routers.soulseek_router",
    Path(__file__).resolve().parents[1] / "app" / "routers" / "soulseek_router.py",
)
assert _SOULSEEK_MODULE_SPEC is not None and _SOULSEEK_MODULE_SPEC.loader is not None
_soulseek_module = importlib.util.module_from_spec(_SOULSEEK_MODULE_SPEC)
_SOULSEEK_MODULE_SPEC.loader.exec_module(_soulseek_module)
router = _soulseek_module.router


class _MockSoulseekClient:
    def __init__(self) -> None:
        self.search = AsyncMock()
        self.download = AsyncMock(
            side_effect=AssertionError("download should not be invoked during tests")
        )
        self.cancel_download = AsyncMock()
        self.get_download = AsyncMock()
        self.get_all_downloads = AsyncMock()
        self.remove_completed_downloads = AsyncMock()
        self.get_queue_position = AsyncMock()
        self.enqueue = AsyncMock()
        self.user_address = AsyncMock()
        self.user_browse = AsyncMock()
        self.user_browsing_status = AsyncMock()
        self.user_directory = AsyncMock()
        self.user_info = AsyncMock()
        self.user_status = AsyncMock()
        self.normalise_search_results = Mock(return_value=[])


@pytest.fixture()
def upload_client_mock() -> Mock:
    client = Mock(spec=SoulseekClient)
    client.cancel_upload = AsyncMock()
    client.get_upload = AsyncMock()
    client.get_uploads = AsyncMock()
    client.get_all_uploads = AsyncMock()
    client.remove_completed_uploads = AsyncMock()
    return client


class _StubSyncWorker:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)


class _FailingSyncWorker(_StubSyncWorker):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error
        self.attempts = 0

    async def enqueue(self, job: dict[str, Any]) -> None:
        self.attempts += 1
        raise self._error


class _StubDiscographyWorker:
    def __init__(self) -> None:
        self.job_ids: list[int] = []

    async def enqueue(self, job_id: int) -> None:
        self.job_ids.append(job_id)


class _FailingDiscographyWorker(_StubDiscographyWorker):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def enqueue(self, job_id: int) -> None:
        await super().enqueue(job_id)
        raise self._error


class _StubLyricsWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, str, dict[str, Any]]] = []

    async def enqueue(
        self, download_id: int | None, filename: str, track_info: dict[str, Any]
    ) -> None:
        self.calls.append((download_id, filename, track_info))


class _FailingLyricsWorker(_StubLyricsWorker):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def enqueue(
        self, download_id: int | None, filename: str, track_info: dict[str, Any]
    ) -> None:
        await super().enqueue(download_id, filename, track_info)
        raise self._error


class _StubMetadataWorker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(
        self,
        download_id: int,
        audio_path: Path,
        *,
        payload: dict[str, Any] | None = None,
        request_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "download_id": download_id,
                "audio_path": audio_path,
                "payload": payload,
                "request_payload": request_payload,
            }
        )
        return {}


class _StubArtworkWorker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(
        self,
        download_id: int,
        audio_path: str,
        **kwargs: Any,
    ) -> None:
        self.calls.append(
            {
                "download_id": download_id,
                "audio_path": audio_path,
                "kwargs": kwargs,
            }
        )


class _FailingArtworkWorker(_StubArtworkWorker):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def enqueue(
        self,
        download_id: int,
        audio_path: str,
        **kwargs: Any,
    ) -> None:
        await super().enqueue(download_id, audio_path, **kwargs)
        raise self._error


@pytest.fixture()
def soulseek_client() -> Iterator[TestClient]:
    init_db()
    config = load_config()
    config.features.enable_lyrics = True
    config.features.enable_artwork = True
    app = FastAPI()
    app.include_router(router, prefix="/soulseek")

    client_stub = _MockSoulseekClient()

    def _get_db() -> Iterator[Any]:
        with session_scope() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_soulseek_client] = lambda: client_stub
    app.dependency_overrides[get_app_config] = lambda: config

    client = TestClient(app)
    with client as test_client:
        sync_worker = _StubSyncWorker()
        discography_worker = _StubDiscographyWorker()
        lyrics_worker = _StubLyricsWorker()
        metadata_worker = _StubMetadataWorker()
        artwork_worker = _StubArtworkWorker()

        test_client.app.state.sync_worker = sync_worker
        test_client.app.state.discography_worker = discography_worker
        test_client.app.state.lyrics_worker = lyrics_worker
        test_client.app.state.rich_metadata_worker = metadata_worker
        test_client.app.state.artwork_worker = artwork_worker
        test_client.app.state.feature_flags = config.features
        test_client.app.state.soulseek_client = client_stub
        yield test_client


def _downloads_dir() -> Path:
    config = load_config()
    roots = allowed_download_roots(config)
    return roots[0]


@pytest.fixture()
def download_factory(soulseek_client: TestClient) -> Iterator[Callable[..., Download]]:
    created_ids: list[int] = []

    def _create_download(**overrides: Any) -> Download:
        defaults: dict[str, Any] = {
            "filename": str(_downloads_dir() / "test.mp3"),
            "state": "failed",
            "progress": 0.0,
            "priority": 0,
            "username": "tester",
            "retry_count": 1,
            "request_payload": {
                "file": {
                    "filename": "test.mp3",
                    "priority": 0,
                },
                "username": "tester",
                "priority": 0,
            },
        }
        defaults.update(overrides)

        with session_scope() as session:
            download = Download(**defaults)
            session.add(download)
            session.commit()
            session.refresh(download)
            created_ids.append(download.id)
            return download

    yield _create_download

    with session_scope() as session:
        for download_id in created_ids:
            record = session.get(Download, download_id)
            if record is not None:
                session.delete(record)
        session.commit()


def test_download_rejects_absolute_filename(soulseek_client: TestClient) -> None:
    response = soulseek_client.post(
        "/soulseek/download",
        json={
            "username": "tester",
            "files": [{"filename": "/tmp/owned.mp3"}],
        },
    )

    assert response.status_code == 400
    assert not Path("/tmp/owned.mp3").exists()


def test_soulseek_search_includes_normalised_results(
    soulseek_client: TestClient,
) -> None:
    client_stub = soulseek_client.app.state.soulseek_client
    raw_payload = {
        "results": [
            {
                "username": "listener",
                "files": [
                    {
                        "id": 42,
                        "filename": "Listener - Track.flac",
                        "bitrate": 1000,
                    }
                ],
            }
        ]
    }
    normalised_entries = [
        {
            "id": "42",
            "filename": "Listener - Track.flac",
            "bitrate": 1000,
            "username": "listener",
        }
    ]
    client_stub.search.return_value = raw_payload
    client_stub.normalise_search_results.return_value = normalised_entries

    response = soulseek_client.post("/soulseek/search", json={"query": "listener"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"] == raw_payload["results"]
    assert payload["raw"] == raw_payload
    assert payload["normalised"] == normalised_entries
    client_stub.normalise_search_results.assert_called_once_with(raw_payload)
    with session_scope() as session:
        assert session.query(Download).count() == 0


def test_soulseek_search_forwards_filters(soulseek_client: TestClient) -> None:
    client_stub = soulseek_client.app.state.soulseek_client
    client_stub.search.return_value = {"results": []}
    client_stub.normalise_search_results.return_value = []

    response = soulseek_client.post(
        "/soulseek/search",
        json={
            "query": " listener ",
            "min_bitrate": 256,
            "preferred_formats": [" FLAC ", "MP3 320"],
        },
    )

    assert response.status_code == 200
    client_stub.search.assert_awaited_once_with(
        "listener",
        min_bitrate=256,
        format_priority=("FLAC", "MP3 320"),
    )


def test_download_rejects_parent_directory_filename(soulseek_client: TestClient) -> None:
    response = soulseek_client.post(
        "/soulseek/download",
        json={
            "username": "tester",
            "files": [{"filename": "../../evil.lrc"}],
        },
    )

    assert response.status_code == 400
    assert not (_downloads_dir().parent / "evil.lrc").exists()
    with session_scope() as session:
        assert session.query(Download).count() == 0


def test_download_accepts_relative_and_normalises(soulseek_client: TestClient) -> None:
    payload = {
        "username": "tester",
        "files": [{"filename": "album/song.mp3"}],
    }

    response = soulseek_client.post("/soulseek/download", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"

    downloads_dir = _downloads_dir()
    expected_path = downloads_dir / "album" / "song.mp3"

    with session_scope() as session:
        stored = session.query(Download).one()
        assert Path(stored.filename) == expected_path

        stored_payload = dict(stored.request_payload or {})

    sync_worker: _StubSyncWorker = soulseek_client.app.state.sync_worker
    assert sync_worker.jobs
    job_payload = sync_worker.jobs[0]
    job_file = job_payload["files"][0]
    assert job_file["filename"] == "album/song.mp3"
    file_metadata = stored_payload.get("file") if isinstance(stored_payload, dict) else None
    assert file_metadata and file_metadata.get("local_path") == str(expected_path)


def test_download_marks_failed_when_worker_errors(soulseek_client: TestClient) -> None:
    error = RuntimeError("sync worker rejected job")
    failing_worker = _FailingSyncWorker(error)
    soulseek_client.app.state.sync_worker = failing_worker

    response = soulseek_client.post(
        "/soulseek/download",
        json={
            "username": "tester",
            "files": [{"filename": "failure/single.mp3"}],
        },
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Soulseek download failed"}
    assert failing_worker.attempts == 1
    assert failing_worker.jobs == []

    expected_path = _downloads_dir() / "failure" / "single.mp3"
    with session_scope() as session:
        download = session.query(Download).filter_by(filename=str(expected_path)).one()
        assert download.state == "failed"
        assert download.last_error == str(error)
        assert download.progress >= 0


def test_download_marks_failed_when_worker_raises_client_error(
    soulseek_client: TestClient,
) -> None:
    class _ClientErrorWorker(_StubSyncWorker):
        async def enqueue(self, job: dict[str, Any]) -> None:
            raise SoulseekClientError("queue rejected")

    soulseek_client.app.state.sync_worker = _ClientErrorWorker()

    response = soulseek_client.post(
        "/soulseek/download",
        json={
            "username": "tester",
            "files": [{"filename": "client-error/single.mp3"}],
        },
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Soulseek download failed"}

    expected_path = _downloads_dir() / "client-error" / "single.mp3"
    with session_scope() as session:
        download = session.query(Download).filter_by(filename=str(expected_path)).one()
        assert download.state == "failed"
        assert download.last_error == "queue rejected"


def test_download_marks_all_failed_when_worker_errors_multiple_files(
    soulseek_client: TestClient,
) -> None:
    error = RuntimeError("sync worker failed for batch")
    failing_worker = _FailingSyncWorker(error)
    soulseek_client.app.state.sync_worker = failing_worker

    filenames = ["failure/multi_one.mp3", "failure/multi_two.mp3"]
    response = soulseek_client.post(
        "/soulseek/download",
        json={
            "username": "tester",
            "files": [{"filename": name} for name in filenames],
        },
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Soulseek download failed"}
    assert failing_worker.attempts == 1
    assert failing_worker.jobs == []

    expected_paths = {str(_downloads_dir() / path) for path in filenames}
    with session_scope() as session:
        downloads = (
            session.query(Download).filter(Download.filename.in_(list(expected_paths))).all()
        )
        assert len(downloads) == len(expected_paths)
        for download in downloads:
            assert download.state == "failed"
            assert download.last_error == str(error)
            assert download.progress >= 0


def test_discography_download_persists_job_and_enqueues(
    soulseek_client: TestClient,
) -> None:
    response = soulseek_client.post(
        "/soulseek/discography/download",
        json={"artist_id": "artist-123", "artist_name": "The Artists"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    job_id = payload["job_id"]

    with session_scope() as session:
        job = session.get(DiscographyJob, job_id)
        assert job is not None
        assert job.artist_id == "artist-123"
        assert job.artist_name == "The Artists"
        assert job.status == "pending"
        session.delete(job)

    worker = soulseek_client.app.state.discography_worker
    assert isinstance(worker, _StubDiscographyWorker)
    assert worker.job_ids == [job_id]


def test_discography_download_rejects_missing_artist_id(
    soulseek_client: TestClient,
) -> None:
    response = soulseek_client.post(
        "/soulseek/discography/download",
        json={"artist_id": "", "artist_name": "Nameless"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Artist identifier is required"}

    with session_scope() as session:
        assert session.query(DiscographyJob).count() == 0


def test_discography_download_marks_job_failed_when_worker_enqueue_errors(
    soulseek_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    error = RuntimeError("discography worker offline")
    failing_worker = _FailingDiscographyWorker(error)
    soulseek_client.app.state.discography_worker = failing_worker
    caplog.set_level("ERROR")
    artist_id = "artist-500"

    response = soulseek_client.post(
        "/soulseek/discography/download",
        json={"artist_id": artist_id, "artist_name": "Offline"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Failed to enqueue discography job"}

    worker = soulseek_client.app.state.discography_worker
    assert isinstance(worker, _FailingDiscographyWorker)

    with session_scope() as session:
        job = (
            session.query(DiscographyJob)
            .filter(DiscographyJob.artist_id == artist_id)
            .one()
        )
        assert job.status == "failed"
        job_id = job.id
        session.delete(job)
        session.commit()

    assert worker.job_ids == [job_id]

    error_messages = [record.message for record in caplog.records if record.levelname == "ERROR"]
    assert any(
        f"Failed to enqueue discography job {job_id}" in message for message in error_messages
    )


def test_discography_download_returns_503_when_worker_missing(
    soulseek_client: TestClient,
) -> None:
    soulseek_client.app.state.discography_worker = None
    artist_id = f"missing-worker-{uuid4().hex}"

    response = soulseek_client.post(
        "/soulseek/discography/download",
        json={"artist_id": artist_id, "artist_name": "Missing Worker"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Discography worker unavailable"}

    with session_scope() as session:
        job = session.query(DiscographyJob).filter(DiscographyJob.artist_id == artist_id).one()
        assert job.status == "failed"
        session.delete(job)
        session.commit()


@pytest.mark.asyncio()
async def test_soulseek_upload_detail_success(upload_client_mock: Mock) -> None:
    expected = {"id": "upload-1", "status": "active"}
    upload_client_mock.get_upload.return_value = expected

    result = await _soulseek_module.soulseek_upload_detail("upload-1", client=upload_client_mock)

    assert result == expected
    upload_client_mock.get_upload.assert_awaited_once_with("upload-1")


@pytest.mark.asyncio()
async def test_soulseek_upload_detail_error(upload_client_mock: Mock) -> None:
    upload_client_mock.get_upload.side_effect = SoulseekClientError("boom")

    with pytest.raises(HTTPException) as exc_info:
        await _soulseek_module.soulseek_upload_detail("upload-2", client=upload_client_mock)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Failed to fetch upload"
    upload_client_mock.get_upload.assert_awaited_once_with("upload-2")


@pytest.mark.asyncio()
@pytest.mark.parametrize("status_code", [401, 403])
async def test_soulseek_upload_detail_auth_error_propagates_status_and_detail(
    upload_client_mock: Mock, status_code: int
) -> None:
    payload = {"detail": f"auth-{status_code}"}
    upload_client_mock.get_upload.side_effect = SoulseekClientError(
        "auth error",
        status_code=status_code,
        payload=payload,
    )

    with pytest.raises(HTTPException) as exc_info:
        await _soulseek_module.soulseek_upload_detail("upload-auth", client=upload_client_mock)

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail == payload
    upload_client_mock.get_upload.assert_awaited_once_with("upload-auth")


@pytest.mark.asyncio()
async def test_soulseek_uploads_success(upload_client_mock: Mock) -> None:
    expected = [{"id": "u1"}, {"id": "u2"}]
    upload_client_mock.get_uploads.return_value = expected

    result = await _soulseek_module.soulseek_uploads(client=upload_client_mock)

    assert result == {"uploads": expected}
    upload_client_mock.get_uploads.assert_awaited_once_with()


@pytest.mark.asyncio()
async def test_soulseek_uploads_error(upload_client_mock: Mock) -> None:
    upload_client_mock.get_uploads.side_effect = SoulseekClientError("fail")

    with pytest.raises(HTTPException) as exc_info:
        await _soulseek_module.soulseek_uploads(client=upload_client_mock)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Failed to fetch uploads"
    upload_client_mock.get_uploads.assert_awaited_once_with()


@pytest.mark.asyncio()
async def test_soulseek_all_uploads_success(upload_client_mock: Mock) -> None:
    expected = [{"id": "u1"}]
    upload_client_mock.get_all_uploads.return_value = expected

    result = await _soulseek_module.soulseek_all_uploads(client=upload_client_mock)

    assert result == {"uploads": expected}
    upload_client_mock.get_all_uploads.assert_awaited_once_with()


@pytest.mark.asyncio()
async def test_soulseek_all_uploads_error(upload_client_mock: Mock) -> None:
    upload_client_mock.get_all_uploads.side_effect = SoulseekClientError("error")

    with pytest.raises(HTTPException) as exc_info:
        await _soulseek_module.soulseek_all_uploads(client=upload_client_mock)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Failed to fetch all uploads"
    upload_client_mock.get_all_uploads.assert_awaited_once_with()


@pytest.mark.asyncio()
async def test_soulseek_remove_completed_uploads_success(
    upload_client_mock: Mock,
) -> None:
    expected = {"removed": 3}
    upload_client_mock.remove_completed_uploads.return_value = expected

    result = await _soulseek_module.soulseek_remove_completed_uploads(client=upload_client_mock)

    assert result == expected
    upload_client_mock.remove_completed_uploads.assert_awaited_once_with()


@pytest.mark.asyncio()
async def test_soulseek_remove_completed_uploads_error(
    upload_client_mock: Mock,
) -> None:
    upload_client_mock.remove_completed_uploads.side_effect = SoulseekClientError("nope")

    with pytest.raises(HTTPException) as exc_info:
        await _soulseek_module.soulseek_remove_completed_uploads(client=upload_client_mock)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Failed to remove completed uploads"
    upload_client_mock.remove_completed_uploads.assert_awaited_once_with()


@pytest.mark.asyncio()
async def test_soulseek_cancel_upload_success(upload_client_mock: Mock) -> None:
    expected = {"cancelled": True}
    upload_client_mock.cancel_upload.return_value = expected

    result = await _soulseek_module.soulseek_cancel_upload("upload-3", client=upload_client_mock)

    assert result == expected
    upload_client_mock.cancel_upload.assert_awaited_once_with("upload-3")


@pytest.mark.asyncio()
async def test_soulseek_cancel_upload_error(upload_client_mock: Mock) -> None:
    upload_client_mock.cancel_upload.side_effect = SoulseekClientError("kaboom")

    with pytest.raises(HTTPException) as exc_info:
        await _soulseek_module.soulseek_cancel_upload("upload-4", client=upload_client_mock)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Failed to cancel upload"
    upload_client_mock.cancel_upload.assert_awaited_once_with("upload-4")


_USER_ENDPOINT_CASES = [
    pytest.param(
        "/soulseek/user/alice/address",
        "user_address",
        {"ip": "127.0.0.1"},
        "Failed to fetch user address",
        ("alice",),
        None,
        id="address",
    ),
    pytest.param(
        "/soulseek/user/alice/browse",
        "user_browse",
        {"files": []},
        "Failed to browse user",
        ("alice",),
        None,
        id="browse",
    ),
    pytest.param(
        "/soulseek/user/alice/browsing_status",
        "user_browsing_status",
        {"status": "active"},
        "Failed to fetch user browsing status",
        ("alice",),
        None,
        id="browsing-status",
    ),
    pytest.param(
        "/soulseek/user/alice/directory",
        "user_directory",
        {"directories": []},
        "Failed to fetch user directory",
        ("alice", "Music/Albums"),
        {"path": "Music/Albums"},
        id="directory",
    ),
    pytest.param(
        "/soulseek/user/alice/info",
        "user_info",
        {"username": "alice"},
        "Failed to fetch user info",
        ("alice",),
        None,
        id="info",
    ),
    pytest.param(
        "/soulseek/user/alice/status",
        "user_status",
        {"online": True},
        "Failed to fetch user status",
        ("alice",),
        None,
        id="status",
    ),
]


@pytest.mark.parametrize(
    (
        "endpoint",
        "client_method",
        "payload",
        "_error_detail",
        "expected_call_args",
        "query_params",
    ),
    _USER_ENDPOINT_CASES,
)
def test_soulseek_user_routes_success(
    soulseek_client: TestClient,
    endpoint: str,
    client_method: str,
    payload: dict[str, Any],
    _error_detail: str,
    expected_call_args: tuple[Any, ...],
    query_params: dict[str, str] | None,
) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    method_mock: AsyncMock = getattr(client_stub, client_method)
    method_mock.return_value = payload

    response = soulseek_client.get(endpoint, params=query_params)

    assert response.status_code == 200
    assert response.json() == payload
    method_mock.assert_awaited_once_with(*expected_call_args)


@pytest.mark.parametrize(
    (
        "endpoint",
        "client_method",
        "_payload",
        "error_detail",
        "expected_call_args",
        "query_params",
    ),
    _USER_ENDPOINT_CASES,
)
def test_soulseek_user_routes_failure(
    soulseek_client: TestClient,
    endpoint: str,
    client_method: str,
    _payload: dict[str, Any],
    error_detail: str,
    expected_call_args: tuple[Any, ...],
    query_params: dict[str, str] | None,
) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    method_mock: AsyncMock = getattr(client_stub, client_method)
    method_mock.side_effect = SoulseekClientError("boom")

    response = soulseek_client.get(endpoint, params=query_params)

    assert response.status_code == 502
    assert response.json() == {"detail": error_detail}
    method_mock.assert_awaited_once_with(*expected_call_args)


def test_lyrics_refresh_rejects_invalid_paths(soulseek_client: TestClient) -> None:
    with session_scope() as session:
        download = Download(
            filename="/tmp/owned.mp3",
            state="completed",
            progress=1.0,
            username="tester",
        )
        session.add(download)
        session.commit()
        download_id = download.id

    response = soulseek_client.post(f"/soulseek/download/{download_id}/lyrics/refresh")

    assert response.status_code == 400
    lyrics_worker: _StubLyricsWorker = soulseek_client.app.state.lyrics_worker
    assert not lyrics_worker.calls


def test_download_lyrics_returns_file_content(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    lyrics_dir = _downloads_dir()
    lyrics_path = lyrics_dir / f"lyrics-{uuid4().hex}.lrc"
    lyrics_path.parent.mkdir(parents=True, exist_ok=True)
    sample_content = "[00:00.00] sample lyrics"

    try:
        lyrics_path.write_text(sample_content, encoding="utf-8")
        download = download_factory(
            state="completed",
            progress=1.0,
            has_lyrics=True,
            lyrics_status="done",
            lyrics_path=str(lyrics_path),
        )

        response = soulseek_client.get(f"/soulseek/download/{download.id}/lyrics")

        assert response.status_code == 200
        assert response.text == sample_content
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
    finally:
        if lyrics_path.exists():
            lyrics_path.unlink()


def test_lyrics_refresh_enqueues_job(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"track-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    download = download_factory(
        state="completed",
        progress=1.0,
        filename=str(audio_path),
    )

    response = soulseek_client.post(f"/soulseek/download/{download.id}/lyrics/refresh")

    assert response.status_code == 202
    assert response.json() == {"status": "queued"}

    lyrics_worker = soulseek_client.app.state.lyrics_worker
    assert isinstance(lyrics_worker, _StubLyricsWorker)
    assert len(lyrics_worker.calls) == 1
    call_download_id, call_filename, track_info = lyrics_worker.calls[0]
    expected_path = str(audio_path.resolve())

    assert call_download_id == download.id
    assert call_filename == expected_path
    assert track_info["download_id"] == download.id
    assert track_info["filename"] == expected_path


def test_lyrics_refresh_returns_503_when_worker_missing(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"missing-worker-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    download = download_factory(
        state="completed",
        progress=1.0,
        filename=str(audio_path),
    )

    soulseek_client.app.state.lyrics_worker = None

    response = soulseek_client.post(f"/soulseek/download/{download.id}/lyrics/refresh")

    assert response.status_code == 503
    assert response.json() == {"detail": "Lyrics worker unavailable"}


def test_lyrics_refresh_returns_502_when_worker_enqueue_fails(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"lyrics-worker-failure-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    download = download_factory(
        state="completed",
        progress=1.0,
        filename=str(audio_path),
        has_lyrics=True,
        lyrics_status="done",
    )

    failing_worker = _FailingLyricsWorker(RuntimeError("enqueue failed"))
    soulseek_client.app.state.lyrics_worker = failing_worker

    response = soulseek_client.post(f"/soulseek/download/{download.id}/lyrics/refresh")

    assert response.status_code == 502
    assert response.json() == {"detail": "Failed to refresh lyrics"}
    assert len(failing_worker.calls) == 1

    with session_scope() as session:
        refreshed = session.get(Download, download.id)
        assert refreshed is not None
        assert refreshed.lyrics_status == "done"
        assert refreshed.has_lyrics is True


def test_artwork_detail_rejects_invalid_paths(soulseek_client: TestClient) -> None:
    with session_scope() as session:
        download = Download(
            filename=str(_downloads_dir() / "invalid-artwork.mp3"),
            state="completed",
            progress=1.0,
            username="tester",
            has_artwork=True,
            artwork_status="done",
            artwork_path="../../escape.png",
        )
        session.add(download)
        session.commit()
        download_id = download.id

    response = soulseek_client.get(f"/soulseek/download/{download_id}/artwork")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid artwork path"}


def test_artwork_detail_returns_404_when_file_missing(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    artwork_path = downloads_dir / f"missing-artwork-{uuid4().hex}.png"
    artwork_path.parent.mkdir(parents=True, exist_ok=True)

    download = download_factory(
        state="completed",
        progress=1.0,
        has_artwork=True,
        artwork_status="done",
        artwork_path=str(artwork_path),
    )

    response = soulseek_client.get(f"/soulseek/download/{download.id}/artwork")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artwork file not found"}


def test_artwork_detail_returns_binary_content(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    artwork_path = downloads_dir / f"artwork-{uuid4().hex}.png"
    artwork_path.parent.mkdir(parents=True, exist_ok=True)
    sample_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00IHDR"

    try:
        artwork_path.write_bytes(sample_bytes)
        download = download_factory(
            state="completed",
            progress=1.0,
            has_artwork=True,
            artwork_status="done",
            artwork_path=str(artwork_path),
        )

        response = soulseek_client.get(f"/soulseek/download/{download.id}/artwork")

        assert response.status_code == 200
        assert response.content == sample_bytes
        assert response.headers["content-type"] == "image/png"
    finally:
        if artwork_path.exists():
            artwork_path.unlink()


def test_metadata_refresh_rejects_invalid_paths(soulseek_client: TestClient) -> None:
    with session_scope() as session:
        download = Download(
            filename="../../escape.mp3",
            state="completed",
            progress=1.0,
            username="tester",
        )
        session.add(download)
        session.commit()
        download_id = download.id

    response = soulseek_client.post(f"/soulseek/download/{download_id}/metadata/refresh")

    assert response.status_code == 400
    metadata_worker: _StubMetadataWorker = soulseek_client.app.state.rich_metadata_worker
    assert not metadata_worker.calls


def test_metadata_detail_returns_serialised_payload(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"metadata-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    request_payload = {
        "metadata": {"album": "Test Album", "title": "Test Title"},
        "file": {"filename": "metadata/test.mp3", "priority": 5},
        "username": "tester",
    }

    try:
        audio_path.touch()
        download = download_factory(
            state="completed",
            progress=1.0,
            filename=str(audio_path),
            genre="Ambient",
            composer="Composer Name",
            producer="Producer Name",
            isrc="US-TEST-12345",
            copyright="2024 Example",
            request_payload=request_payload,
        )

        response = soulseek_client.get(f"/soulseek/download/{download.id}/metadata")

        assert response.status_code == 200
        assert response.json() == {
            "id": download.id,
            "filename": str(audio_path),
            "genre": "Ambient",
            "composer": "Composer Name",
            "producer": "Producer Name",
            "isrc": "US-TEST-12345",
            "copyright": "2024 Example",
        }
    finally:
        if audio_path.exists():
            audio_path.unlink()


def test_metadata_refresh_enqueues_job(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"metadata-refresh-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    request_payload = {
        "metadata": {"artist": "Example Artist"},
        "file": {"filename": "metadata-refresh/test.mp3", "priority": 3},
        "username": "tester",
    }

    try:
        audio_path.touch()
        download = download_factory(
            state="completed",
            progress=1.0,
            filename=str(audio_path),
            request_payload=request_payload,
        )

        response = soulseek_client.post(f"/soulseek/download/{download.id}/metadata/refresh")

        assert response.status_code == 202
        assert response.json() == {"status": "queued"}

        metadata_worker: _StubMetadataWorker = soulseek_client.app.state.rich_metadata_worker
        assert len(metadata_worker.calls) == 1
        call = metadata_worker.calls[0]
        assert call["download_id"] == download.id
        assert call["audio_path"] == audio_path
        assert call["payload"] == request_payload
        assert call["request_payload"] == request_payload
    finally:
        if audio_path.exists():
            audio_path.unlink()


def test_artwork_refresh_enqueues_job(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"artwork-refresh-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    request_payload = {
        "metadata": {"album": "Example Album"},
        "file": {"filename": "artwork-refresh/test.mp3", "priority": 4},
        "spotify_album_id": "album-123",
        "artwork_urls": ["https://example.com/cover.jpg"],
    }

    try:
        audio_path.touch()
        download = download_factory(
            state="completed",
            progress=1.0,
            filename=str(audio_path),
            request_payload=request_payload,
            artwork_url="https://fallback.example.com/cover.jpg",
        )

        response = soulseek_client.post(f"/soulseek/download/{download.id}/artwork/refresh")

        assert response.status_code == 202
        assert response.json() == {"status": "pending"}

        worker = soulseek_client.app.state.artwork_worker
        assert isinstance(worker, _StubArtworkWorker)
        assert len(worker.calls) == 1
        call = worker.calls[0]
        assert call["download_id"] == download.id
        assert call["audio_path"] == str(audio_path.resolve())
        kwargs = call["kwargs"]
        assert kwargs["refresh"] is True
        metadata = kwargs["metadata"]
        assert metadata["album"] == "Example Album"
        assert metadata["spotify_album_id"] == "album-123"
        assert kwargs["spotify_album_id"] == "album-123"
        assert kwargs["artwork_url"] == "https://fallback.example.com/cover.jpg"
        assert metadata["artwork_url"] == "https://fallback.example.com/cover.jpg"

        with session_scope() as session:
            refreshed = session.get(Download, download.id)
            assert refreshed is not None
            assert refreshed.artwork_status == "pending"
            assert refreshed.has_artwork is False
            assert refreshed.artwork_path is None
    finally:
        if audio_path.exists():
            audio_path.unlink()


def test_artwork_refresh_returns_202_when_worker_missing(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"artwork-refresh-missing-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        audio_path.touch()
        download = download_factory(
            state="completed",
            progress=1.0,
            filename=str(audio_path),
        )

        soulseek_client.app.state.artwork_worker = None

        response = soulseek_client.post(f"/soulseek/download/{download.id}/artwork/refresh")

        assert response.status_code == 202
        assert response.json() == {"status": "pending"}
    finally:
        if audio_path.exists():
            audio_path.unlink()


def test_artwork_refresh_returns_502_when_worker_errors(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    downloads_dir = _downloads_dir()
    audio_path = downloads_dir / f"artwork-refresh-error-{uuid4().hex}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        audio_path.touch()
        download = download_factory(
            state="completed",
            progress=1.0,
            filename=str(audio_path),
        )

        soulseek_client.app.state.artwork_worker = _FailingArtworkWorker(RuntimeError("boom"))

        response = soulseek_client.post(f"/soulseek/download/{download.id}/artwork/refresh")

        assert response.status_code == 502
        assert response.json() == {"detail": "Failed to refresh artwork"}

        worker = soulseek_client.app.state.artwork_worker
        assert isinstance(worker, _FailingArtworkWorker)
        assert len(worker.calls) == 1
        assert worker.calls[0]["download_id"] == download.id
    finally:
        if audio_path.exists():
            audio_path.unlink()


def test_requeue_download_success(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory(state="failed", retry_count=3)

    response = soulseek_client.post(f"/soulseek/downloads/{download.id}/requeue")

    assert response.status_code == 202
    assert response.json() == {"status": "enqueued"}

    sync_worker: _StubSyncWorker = soulseek_client.app.state.sync_worker
    assert len(sync_worker.jobs) == 1
    job = sync_worker.jobs[0]
    assert job["username"] == "tester"
    assert job["priority"] == 0
    assert job["files"][0]["download_id"] == download.id

    with session_scope() as session:
        refreshed = session.get(Download, download.id)
        assert refreshed is not None
        assert refreshed.state == "queued"
        assert refreshed.retry_count == 0
        payload = refreshed.request_payload or {}
        assert payload.get("username") == "tester"
        file_payload = payload.get("file") or {}
        assert file_payload.get("download_id") == download.id


def test_requeue_download_dead_letter(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory(state="dead_letter")

    response = soulseek_client.post(f"/soulseek/downloads/{download.id}/requeue")

    assert response.status_code == 409
    assert response.json()["detail"] == "Download is in the dead-letter queue"


def test_requeue_download_missing_file_payload(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory(request_payload={"username": "tester"})

    response = soulseek_client.post(f"/soulseek/downloads/{download.id}/requeue")

    assert response.status_code == 409
    assert response.json()["detail"] == "Download cannot be requeued"


def test_requeue_download_missing_username(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory(
        username=None,
        request_payload={
            "file": {"filename": "test.mp3"},
            "username": "",
        },
    )

    response = soulseek_client.post(f"/soulseek/downloads/{download.id}/requeue")

    assert response.status_code == 409
    assert response.json()["detail"] == "Download username missing for retry"


def test_requeue_download_worker_unavailable(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory()
    soulseek_client.app.state.sync_worker = None

    response = soulseek_client.post(f"/soulseek/downloads/{download.id}/requeue")

    assert response.status_code == 503
    assert response.json()["detail"] == "Sync worker unavailable"


def test_requeue_download_worker_failure(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory()

    class _FailingWorker:
        async def enqueue(self, job: dict[str, Any]) -> None:
            raise RuntimeError("boom")

    soulseek_client.app.state.sync_worker = _FailingWorker()

    response = soulseek_client.post(f"/soulseek/downloads/{download.id}/requeue")

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to requeue download"

    with session_scope() as session:
        refreshed = session.get(Download, download.id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.last_error is not None


def test_cancel_download_success(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory(state="queued", progress=150.0)
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client

    response = soulseek_client.delete(f"/soulseek/download/{download.id}")

    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    client_stub.cancel_download.assert_awaited_once_with(str(download.id))

    with session_scope() as session:
        refreshed = session.get(Download, download.id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.progress == 100.0


def test_cancel_download_client_error(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    download = download_factory(state="queued", progress=50.0)
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.cancel_download.side_effect = SoulseekClientError("failure")

    response = soulseek_client.delete(f"/soulseek/download/{download.id}")

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to cancel download"

    with session_scope() as session:
        refreshed = session.get(Download, download.id)
        assert refreshed is not None
        assert refreshed.state == "queued"


def test_get_downloads_returns_db_entries(
    soulseek_client: TestClient, download_factory: Callable[..., Download]
) -> None:
    first = download_factory(state="completed", progress=1.0, priority=2)
    second = download_factory(state="failed", progress=0.5, priority=1)

    response = soulseek_client.get("/soulseek/downloads")

    assert response.status_code == 200
    payload = response.json()
    assert {entry["id"] for entry in payload["downloads"]} == {first.id, second.id}
    assert payload["retryable_states"]


def test_get_all_downloads_uses_client(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.get_all_downloads.return_value = {"active": []}

    response = soulseek_client.get("/soulseek/downloads/all")

    assert response.status_code == 200
    assert response.json() == {"downloads": {"active": []}}
    client_stub.get_all_downloads.assert_awaited_once()


def test_get_all_downloads_client_error(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.get_all_downloads.side_effect = SoulseekClientError("boom")

    response = soulseek_client.get("/soulseek/downloads/all")

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to fetch downloads"


def test_remove_completed_downloads(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.remove_completed_downloads.return_value = {"removed": 3}

    response = soulseek_client.delete("/soulseek/downloads/completed")

    assert response.status_code == 200
    assert response.json() == {"removed": 3}
    client_stub.remove_completed_downloads.assert_awaited_once()


def test_remove_completed_downloads_client_error(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.remove_completed_downloads.side_effect = SoulseekClientError("boom")

    response = soulseek_client.delete("/soulseek/downloads/completed")

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to remove completed downloads"


def test_get_download_queue(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.get_queue_position.return_value = {"position": 1}

    response = soulseek_client.get("/soulseek/download/123/queue")

    assert response.status_code == 200
    assert response.json() == {"position": 1}
    client_stub.get_queue_position.assert_awaited_once_with("123")


def test_get_download_queue_client_error(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.get_queue_position.side_effect = SoulseekClientError("boom")

    response = soulseek_client.get("/soulseek/download/123/queue")

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to fetch queue position"


def test_get_download_queue_client_error_propagates_status(
    soulseek_client: TestClient,
) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.get_queue_position.side_effect = SoulseekClientError(
        "missing queue",
        status_code=404,
    )

    response = soulseek_client.get("/soulseek/download/123/queue")

    assert response.status_code == 404
    assert response.json()["detail"] == "Failed to fetch queue position"


def test_enqueue_downloads(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.enqueue.return_value = {"enqueued": 2}

    payload = {
        "username": "tester",
        "files": [
            {"filename": "a.mp3", "size": 1, "priority": 0},
            {"filename": "b.mp3", "size": 2, "priority": 1},
        ],
    }

    response = soulseek_client.post("/soulseek/enqueue", json=payload)

    assert response.status_code == 200
    assert response.json() == {"enqueued": 2}
    client_stub.enqueue.assert_awaited_once_with(
        "tester",
        [
            {"filename": "a.mp3", "size": 1, "priority": 0},
            {"filename": "b.mp3", "size": 2, "priority": 1},
        ],
    )


def test_enqueue_downloads_client_error(soulseek_client: TestClient) -> None:
    client_stub: _MockSoulseekClient = soulseek_client.app.state.soulseek_client
    client_stub.enqueue.side_effect = SoulseekClientError("boom")

    payload = {"username": "tester", "files": []}

    response = soulseek_client.post("/soulseek/enqueue", json=payload)

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to enqueue downloads"
