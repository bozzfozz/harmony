from __future__ import annotations

from collections.abc import Iterator
import importlib.util
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.config import load_config
from app.db import init_db, session_scope
from app.dependencies import get_app_config, get_db, get_soulseek_client
from app.models import Download
from app.utils.path_safety import allowed_download_roots

_SOULSEEK_MODULE_SPEC = importlib.util.spec_from_file_location(
    "app.routers.soulseek_router",
    Path(__file__).resolve().parents[1] / "app" / "routers" / "soulseek_router.py",
)
assert _SOULSEEK_MODULE_SPEC is not None and _SOULSEEK_MODULE_SPEC.loader is not None
_soulseek_module = importlib.util.module_from_spec(_SOULSEEK_MODULE_SPEC)
_SOULSEEK_MODULE_SPEC.loader.exec_module(_soulseek_module)
router = _soulseek_module.router


class _StubSoulseekClient:
    async def download(self, payload: dict[str, Any]) -> None:  # pragma: no cover - guard
        raise AssertionError("download should not be invoked during tests")


class _StubSyncWorker:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, job: dict[str, Any]) -> None:
        self.jobs.append(job)


class _StubLyricsWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[int | None, str, dict[str, Any]]] = []

    async def enqueue(
        self, download_id: int | None, filename: str, track_info: dict[str, Any]
    ) -> None:
        self.calls.append((download_id, filename, track_info))


class _StubMetadataWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[int, Path]] = []

    async def enqueue(
        self,
        download_id: int,
        audio_path: Path,
        *,
        payload: dict[str, Any] | None = None,
        request_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((download_id, audio_path))
        return {}


@pytest.fixture()
def soulseek_client() -> Iterator[TestClient]:
    init_db()
    config = load_config()
    config.features.enable_lyrics = True
    config.features.enable_artwork = True
    app = FastAPI()
    app.include_router(router, prefix="/soulseek")

    def _get_db() -> Iterator[Any]:
        with session_scope() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_soulseek_client] = lambda: _StubSoulseekClient()
    app.dependency_overrides[get_app_config] = lambda: config

    client = TestClient(app)
    with client as test_client:
        test_client.app.state.sync_worker = _StubSyncWorker()
        test_client.app.state.lyrics_worker = _StubLyricsWorker()
        test_client.app.state.rich_metadata_worker = _StubMetadataWorker()
        test_client.app.state.feature_flags = config.features
        yield test_client


def _downloads_dir() -> Path:
    config = load_config()
    roots = allowed_download_roots(config)
    return roots[0]


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
    with session_scope() as session:
        assert session.query(Download).count() == 0


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
