from app.db import session_scope
from app.models import ArtistPreference


def test_followed_artists_endpoint(client) -> None:
    stub = client.app.state.spotify_stub
    stub.followed_artists = [
        {"id": "artist-a", "name": "Alpha"},
        {"id": "artist-b", "name": "Beta"},
    ]

    response = client.get("/spotify/artists/followed")
    assert response.status_code == 200
    body = response.json()
    assert {artist["id"] for artist in body["artists"]} == {"artist-a", "artist-b"}


def test_artist_releases_endpoint(client) -> None:
    stub = client.app.state.spotify_stub
    stub.artist_releases["artist-a"] = [
        {"id": "release-1", "name": "First", "album_type": "album"},
        {"id": "release-2", "name": "Second", "album_type": "single"},
    ]

    response = client.get("/spotify/artist/artist-a/releases")
    assert response.status_code == 200
    body = response.json()
    assert body["artist_id"] == "artist-a"
    assert {release["id"] for release in body["releases"]} == {"release-1", "release-2"}


def test_artist_preferences_persist(client) -> None:
    payload = {
        "preferences": [
            {"artist_id": "artist-a", "release_id": "release-1", "selected": True},
            {"artist_id": "artist-a", "release_id": "release-2", "selected": False},
        ]
    }

    save_response = client.post("/settings/artist-preferences", json=payload)
    assert save_response.status_code == 200
    returned = save_response.json()["preferences"]
    assert len(returned) == 2

    list_response = client.get("/settings/artist-preferences")
    assert list_response.status_code == 200
    listed = list_response.json()["preferences"]
    assert listed == returned

    with session_scope() as session:
        records = session.query(ArtistPreference).all()
        assert len(records) == 2
        mapping = {
            (record.artist_id, record.release_id): record.selected for record in records
        }
    assert mapping[("artist-a", "release-1")] is True
    assert mapping[("artist-a", "release-2")] is False
