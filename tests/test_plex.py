"""Integration tests for the Plex backend components."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import SessionLocal, init_db
from backend.app.models.plex_models import PlexAlbum, PlexArtist, PlexTrack
from backend.app.routers import plex_router
from backend.app.workers.plex_worker import PlexWorker


@pytest.fixture(autouse=True)
def prepare_database() -> None:
    """Ensure Plex tables exist and are empty before each test."""

    init_db()
    with SessionLocal() as session:
        session.query(PlexTrack).delete()
        session.query(PlexAlbum).delete()
        session.query(PlexArtist).delete()
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(PlexTrack).delete()
        session.query(PlexAlbum).delete()
        session.query(PlexArtist).delete()
        session.commit()


def test_status_endpoint_reports_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """The status endpoint surfaces the Plex client's connectivity flag."""

    class DummyClient:
        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr(plex_router, "plex_client", DummyClient())

    assert plex_router.plex_status() == {"connected": True}


def test_get_artists_returns_sorted_entries() -> None:
    """Artists are retrieved from the database in alphabetical order."""

    with SessionLocal() as session:
        session.add(PlexArtist(id="2", name="Zeta"))
        session.add(PlexArtist(id="1", name="Alpha"))
        session.commit()

    with SessionLocal() as session:
        response = plex_router.get_artists(db=session)

    assert response == {
        "artists": [
            {"id": "1", "name": "Alpha"},
            {"id": "2", "name": "Zeta"},
        ]
    }


def test_get_albums_requires_existing_artist() -> None:
    """Requesting albums for an unknown artist raises a 404 error."""

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as excinfo:
            plex_router.get_albums("missing", db=session)

    assert excinfo.value.status_code == 404


def test_get_albums_returns_payload_for_artist() -> None:
    """Albums are filtered by artist and returned with basic metadata."""

    with SessionLocal() as session:
        session.add(PlexArtist(id="artist-1", name="Example Artist"))
        session.add(PlexAlbum(id="album-a", title="First", artist_id="artist-1"))
        session.add(PlexAlbum(id="album-b", title="Second", artist_id="artist-1"))
        session.add(PlexAlbum(id="album-c", title="Other", artist_id="another"))
        session.commit()

    with SessionLocal() as session:
        response = plex_router.get_albums("artist-1", db=session)

    assert response == {
        "artist": {"id": "artist-1", "name": "Example Artist"},
        "albums": [
            {"id": "album-a", "title": "First", "artist_id": "artist-1"},
            {"id": "album-b", "title": "Second", "artist_id": "artist-1"},
        ],
    }


def test_get_tracks_requires_existing_album() -> None:
    """Unknown albums yield a 404 error."""

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as excinfo:
            plex_router.get_tracks("missing", db=session)

    assert excinfo.value.status_code == 404


def test_get_tracks_returns_album_tracks() -> None:
    """Tracks are returned for the requested album only."""

    with SessionLocal() as session:
        session.add(PlexArtist(id="artist-1", name="Example Artist"))
        session.add(PlexAlbum(id="album-1", title="Greatest", artist_id="artist-1"))
        session.add(PlexTrack(id="track-1", title="Song A", album_id="album-1", duration=120))
        session.add(PlexTrack(id="track-2", title="Song B", album_id="album-1", duration=None))
        session.add(PlexTrack(id="track-x", title="Other", album_id="album-x", duration=99))
        session.commit()

    with SessionLocal() as session:
        response = plex_router.get_tracks("album-1", db=session)

    assert response == {
        "album": {"id": "album-1", "title": "Greatest", "artist_id": "artist-1"},
        "tracks": [
            {"id": "track-1", "title": "Song A", "album_id": "album-1", "duration": 120},
            {"id": "track-2", "title": "Song B", "album_id": "album-1", "duration": None},
        ],
    }


def test_worker_syncs_data_into_database() -> None:
    """The Plex worker fetches metadata and stores it in SQLite."""

    class FakePlexClient:
        def get_all_artists(self) -> list[dict[str, object]]:
            return [{"id": "artist-1", "name": "Example Artist"}]

        def get_albums_by_artist(self, artist_id: str) -> list[dict[str, object]]:
            assert artist_id == "artist-1"
            return [{"id": "album-1", "title": "Greatest", "artist_id": artist_id}]

        def get_tracks_by_album(self, album_id: str) -> list[dict[str, object]]:
            assert album_id == "album-1"
            return [
                {"id": "track-1", "title": "Song A", "album_id": album_id, "duration": 245},
                {"id": "track-2", "title": "Song B", "album_id": album_id, "duration": None},
            ]

    with SessionLocal() as session:
        session.add(PlexArtist(id="old", name="Old Artist"))
        session.add(PlexAlbum(id="old-album", title="Old", artist_id="old"))
        session.add(PlexTrack(id="old-track", title="Legacy", album_id="old-album", duration=1))
        session.commit()

    worker = PlexWorker(client=FakePlexClient())
    worker.sync()

    with SessionLocal() as session:
        artists = session.query(PlexArtist).order_by(PlexArtist.id).all()
        albums = session.query(PlexAlbum).order_by(PlexAlbum.id).all()
        tracks = session.query(PlexTrack).order_by(PlexTrack.id).all()

    assert [artist.id for artist in artists] == ["artist-1"]
    assert albums[0].title == "Greatest"
    assert albums[0].artist_id == "artist-1"
    assert [track.id for track in tracks] == ["track-1", "track-2"]
    assert tracks[0].duration == 245
