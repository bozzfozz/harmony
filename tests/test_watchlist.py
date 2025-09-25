from __future__ import annotations

from datetime import datetime, timedelta

import asyncio

from sqlalchemy import select

from app.db import session_scope
from app.models import Download, WatchlistArtist
from app.workers.watchlist_worker import WatchlistWorker


def test_add_artist_to_watchlist(client) -> None:
    response = client.post(
        "/watchlist",
        json={"spotify_artist_id": "artist-42", "name": "Example Artist"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["spotify_artist_id"] == "artist-42"
    assert payload["name"] == "Example Artist"

    listing = client.get("/watchlist")
    assert listing.status_code == 200
    body = listing.json()
    assert any(item["spotify_artist_id"] == "artist-42" for item in body["items"])


def test_prevent_duplicate_artists(client) -> None:
    payload = {"spotify_artist_id": "artist-99", "name": "Duplicate"}
    first = client.post("/watchlist", json=payload)
    assert first.status_code == 201

    second = client.post("/watchlist", json=payload)
    assert second.status_code == 409


def _prepare_watchlist_artist(artist_id: str, name: str, *, days_ago: int = 2) -> None:
    with session_scope() as session:
        record = WatchlistArtist(
            spotify_artist_id=artist_id,
            name=name,
            last_checked=datetime.utcnow() - timedelta(days=days_ago),
        )
        session.add(record)


def _configure_stub_data(client, *, track_id: str, album_id: str, track_name: str, album_name: str) -> None:
    spotify_stub = client.app.state.spotify_stub
    soulseek_stub = client.app.state.soulseek_stub

    spotify_stub.artist_albums["artist-watch"] = [
        {
            "id": album_id,
            "name": album_name,
            "artists": [{"name": "Watcher"}],
            "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "release_date_precision": "day",
        }
    ]
    spotify_stub.album_tracks[album_id] = [
        {
            "id": track_id,
            "name": track_name,
            "artists": [{"name": "Watcher"}],
        }
    ]

    full_title = f"Watcher {track_name} {album_name}"
    soulseek_stub.search_results = [
        {
            "username": "watcher-user",
            "files": [
                {
                    "id": "slsk-track",
                    "filename": f"Watcher - {track_name} - {album_name}.flac",
                    "title": full_title,
                    "priority": 0,
                }
            ],
        }
    ]


def _run_worker(client) -> None:
    worker = WatchlistWorker(
        spotify_client=client.app.state.spotify_stub,
        soulseek_client=client.app.state.soulseek_stub,
        sync_worker=client.app.state.sync_worker,
        interval_seconds=0.1,
    )
    loop = asyncio.get_event_loop()
    loop.run_until_complete(worker.run_once())


def test_worker_detects_new_release(client) -> None:
    _prepare_watchlist_artist("artist-watch", "Watcher")
    _configure_stub_data(
        client,
        track_id="track-new",
        album_id="album-new",
        track_name="Fresh Cut",
        album_name="Brand New",
    )

    _run_worker(client)

    with session_scope() as session:
        downloads = session.execute(select(Download)).scalars().all()
        assert any(download.spotify_track_id == "track-new" for download in downloads)
        artist = session.execute(
            select(WatchlistArtist).where(WatchlistArtist.spotify_artist_id == "artist-watch")
        ).scalar_one()
        assert artist.last_checked is not None
        assert artist.last_checked > datetime.utcnow() - timedelta(minutes=5)

    queued = client.app.state.soulseek_stub.downloads
    assert any(
        entry.get("filename") == "Watcher - Fresh Cut - Brand New.flac"
        for entry in queued.values()
    )


def test_worker_no_duplicates(client) -> None:
    _prepare_watchlist_artist("artist-watch", "Watcher")
    _configure_stub_data(
        client,
        track_id="track-dupe",
        album_id="album-dupe",
        track_name="Repeat", 
        album_name="Same Again",
    )

    _run_worker(client)
    _run_worker(client)

    with session_scope() as session:
        downloads = session.execute(select(Download)).scalars().all()
        matching = [d for d in downloads if d.spotify_track_id == "track-dupe"]
        assert len(matching) == 1
