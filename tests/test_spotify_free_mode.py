from __future__ import annotations

from typing import Any, Dict

import pytest

from app.db import session_scope
from app.models import Download
from tests.simple_client import SimpleTestClient


def _make_track(
    *,
    artist: str,
    title: str,
    album: str | None = None,
    year: int | None = None,
    spotify_track_id: str | None = None,
    spotify_album_id: str | None = None,
) -> Dict[str, Any]:
    query_parts = [title, artist]
    if album:
        query_parts.append(album)
    if year:
        query_parts.append(str(year))
    query = " ".join(query_parts)
    return {
        "source": "user",
        "kind": "track",
        "artist": artist,
        "title": title,
        "album": album,
        "release_year": year,
        "spotify_track_id": spotify_track_id,
        "spotify_album_id": spotify_album_id,
        "query": query,
    }


def test_spotify_free_parse_lines(client: SimpleTestClient) -> None:
    payload = {
        "lines": [
            "Radiohead - Paranoid Android | OK Computer | 1997",
            "Arcade Fire - Wake Up | Funeral",
            "Sigur Rós - Svefn-g-englar https://open.spotify.com/track/abc123?si=xyz",
        ]
    }
    response = client.post("/spotify/free/parse", json=payload)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 3
    assert items[0]["artist"] == "Radiohead"
    assert items[0]["release_year"] == 1997
    assert items[1]["album"] == "Funeral"
    assert items[2]["spotify_track_id"] == "abc123"
    assert items[2]["query"].startswith("Svefn-g-englar")


def test_spotify_free_parse_album_error(client: SimpleTestClient) -> None:
    response = client.post(
        "/spotify/free/parse",
        json={"lines": ["https://open.spotify.com/album/zzz111"]},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_spotify_free_parse_line_limit(client: SimpleTestClient) -> None:
    payload = {"lines": [f"Artist {index} - Title {index}" for index in range(205)]}
    response = client.post("/spotify/free/parse", json=payload)
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_spotify_free_enqueue_batches(client: SimpleTestClient) -> None:
    items = [
        _make_track(artist="Soulseek Artist", title="Test Song", year=1969),
        _make_track(artist="Soulseek Artist", title="Other Track"),
        _make_track(artist="Soulseek Artist", title="Test Song", year=1969),
    ]
    response = client.post("/spotify/free/enqueue", json={"items": items})
    assert response.status_code == 200
    payload = response.json()
    assert payload["queued"] == 2
    assert payload["skipped"] == 1

    with session_scope() as session:
        downloads = session.query(Download).order_by(Download.id.asc()).all()
        assert len(downloads) == 2
        filenames = {download.filename for download in downloads}
        assert any("Test Song" in name for name in filenames)
        assert any("Other Track" in name for name in filenames)

    stub = client.app.state.soulseek_stub
    assert len(stub.downloads) == 2


@pytest.mark.parametrize(
    "line",
    [
        " ",
        "ArtistOnly",
        "https://open.spotify.com/playlist/abc999",
    ],
)
def test_spotify_free_parse_invalid_lines(client: SimpleTestClient, line: str) -> None:
    response = client.post("/spotify/free/parse", json={"lines": [line]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
