import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/spotify/status",
        "/spotify/backfill/jobs/sample",
    ],
)
def test_spotify_routes_registered(client, path: str) -> None:
    response = client.get(path)
    if "backfill" in path:
        assert response.status_code in {200, 404}
    else:
        assert response.status_code == 200
