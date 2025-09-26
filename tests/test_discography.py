from __future__ import annotations

import pytest

from app.db import session_scope
from app.models import DiscographyJob
from app.workers.discography_worker import DiscographyWorker


class SpotifyDiscographyStub:
    def __init__(self, albums: list[dict]) -> None:
        self.albums = albums
        self.requests: list[str] = []

    def get_artist_discography(self, artist_id: str) -> dict:
        self.requests.append(artist_id)
        return {"artist_id": artist_id, "albums": list(self.albums)}


class PlexDiscographyStub:
    def __init__(self, track_ids: list[str]) -> None:
        self.track_ids = track_ids
        self.lookups: list[str] = []

    async def get_artist_tracks(self, artist_name: str) -> list[dict]:
        self.lookups.append(artist_name)
        return [{"guid": f"spotify://track:{track_id}"} for track_id in self.track_ids]


class SoulseekDiscographyStub:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.download_payloads: list[dict] = []

    async def search(self, query: str) -> dict:
        self.search_queries.append(query)
        return {
            "results": [
                {
                    "username": "collector",
                    "files": [
                        {
                            "filename": f"{query}.flac",
                            "size": 1024,
                        }
                    ],
                }
            ]
        }

    async def download(self, payload: dict) -> None:
        self.download_payloads.append(payload)


class BeetsImportStub:
    def __init__(self) -> None:
        self.imports: list[str] = []

    def import_file(self, path: str, quiet: bool = True) -> str:  # pragma: no cover - simple stub
        self.imports.append(path)
        return path


def _create_job(artist_id: str, artist_name: str) -> int:
    with session_scope() as session:
        job = DiscographyJob(artist_id=artist_id, artist_name=artist_name, status="pending")
        session.add(job)
        session.flush()
        return job.id


@pytest.mark.asyncio
async def test_discography_worker_processes_complete_discography() -> None:
    albums = [
        {
            "album": {"id": "album-1", "name": "First"},
            "tracks": [
                {"id": "track-1", "name": "Track One"},
                {"id": "track-2", "name": "Track Two"},
            ],
        },
        {
            "album": {"id": "album-2", "name": "Second"},
            "tracks": [
                {"id": "track-3", "name": "Track Three"},
            ],
        },
    ]
    spotify = SpotifyDiscographyStub(albums)
    plex = PlexDiscographyStub(track_ids=[])
    soulseek = SoulseekDiscographyStub()
    beets = BeetsImportStub()

    worker = DiscographyWorker(
        spotify,
        soulseek,
        plex_client=plex,
        beets_client=beets,
    )

    job_id = _create_job("artist-1", "Test Artist")

    await worker.run_job(job_id)

    with session_scope() as session:
        job = session.get(DiscographyJob, job_id)
        assert job is not None
        assert job.status == "done"

    assert spotify.requests == ["artist-1"]
    assert len(soulseek.download_payloads) == 3
    assert len(beets.imports) == 3


@pytest.mark.asyncio
async def test_discography_worker_downloads_only_missing_tracks() -> None:
    albums = [
        {
            "album": {"id": "album-1", "name": "First"},
            "tracks": [
                {"id": "track-1", "name": "Track One"},
                {"id": "track-2", "name": "Track Two"},
            ],
        }
    ]
    spotify = SpotifyDiscographyStub(albums)
    plex = PlexDiscographyStub(track_ids=["track-1"])
    soulseek = SoulseekDiscographyStub()
    beets = BeetsImportStub()

    worker = DiscographyWorker(
        spotify,
        soulseek,
        plex_client=plex,
        beets_client=beets,
    )

    job_id = _create_job("artist-2", "Another Artist")

    await worker.run_job(job_id)

    with session_scope() as session:
        job = session.get(DiscographyJob, job_id)
        assert job is not None
        assert job.status == "done"

    assert len(soulseek.download_payloads) == 1
    assert soulseek.download_payloads[0]["files"][0]["filename"].startswith(
        "Another Artist Track Two"
    )


def test_discography_download_endpoint_persists_job(client) -> None:
    response = client.post(
        "/soulseek/discography/download",
        json={"artist_id": "artist-3", "artist_name": "Integration"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"

    job_id = payload["job_id"]
    with session_scope() as session:
        job = session.get(DiscographyJob, job_id)
        assert job is not None
        assert job.artist_id == "artist-3"
        assert job.artist_name == "Integration"
