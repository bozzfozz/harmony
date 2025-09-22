import asyncio

from app.routers import plex_router


def test_status_endpoint_reports_connection():
    async def runner():
        response = await plex_router.status()
        assert response == {"plex_connected": True}

    asyncio.run(runner())


def test_list_libraries_returns_stub_data():
    async def runner():
        response = await plex_router.list_libraries()
        assert response.model_dump() == {"libraries": ["Music"]}

    asyncio.run(runner())


def test_search_tracks_returns_matching_tracks():
    async def runner():
        response = await plex_router.search_tracks(query="song")
        assert response.model_dump() == {
            "tracks": [
                {
                    "title": "Song One",
                    "artist": "Artist A",
                    "album": "Album X",
                    "duration": 210,
                },
                {
                    "title": "Song Two",
                    "artist": "Artist B",
                    "album": "Album Y",
                    "duration": 198,
                },
            ]
        }

    asyncio.run(runner())


def test_search_albums_returns_matching_albums():
    async def runner():
        response = await plex_router.search_albums(query="album")
        assert response.model_dump() == {
            "albums": [
                {"title": "Album X", "artist": "Artist A", "year": 2020, "track_count": 1},
                {"title": "Album Y", "artist": "Artist B", "year": 2019, "track_count": 1},
            ]
        }

    asyncio.run(runner())


def test_get_artists_endpoint():
    async def runner():
        response = await plex_router.get_artists()
        assert response == {"artists": ["Artist A", "Artist B", "Different"]}

    asyncio.run(runner())
