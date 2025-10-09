from __future__ import annotations

from app import dependencies as deps
from app.utils.settings_store import write_setting
from tests.simple_client import SimpleTestClient


def test_spotify_status_reports_capabilities(client: SimpleTestClient) -> None:
    response = client.get("/spotify/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["free_available"] is True
    assert payload["pro_available"] is True
    assert payload["status"] in {"connected", "unauthenticated"}


def test_spotify_pro_features_require_credentials(
    client: SimpleTestClient, monkeypatch
) -> None:
    from app.dependencies import get_spotify_client as dependency_spotify_client

    # Prime the cache to ensure the status endpoint does not serve stale data after credential changes.
    baseline = client.get("/spotify/status")
    assert baseline.status_code == 200
    assert baseline.json()["status"] != "unconfigured"

    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI"):
        write_setting(key, "")

    deps.get_app_config.cache_clear()
    if hasattr(deps.get_spotify_client, "cache_clear"):
        deps.get_spotify_client.cache_clear()

    stub_spotify = client.app.state.spotify_stub
    monkeypatch.setattr(deps, "get_spotify_client", lambda: None)
    client.app.dependency_overrides[dependency_spotify_client] = lambda: None

    try:
        status = client.get("/spotify/status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["pro_available"] is False
        assert payload["status"] == "unconfigured"

        response = client.get("/spotify/search/tracks", params={"query": "test"})
        assert response.status_code == 503
        error_payload = response.json()
        assert error_payload["ok"] is False
        assert error_payload["error"]["code"] == "DEPENDENCY_ERROR"
        assert "Spotify credentials" in error_payload["error"]["message"]
    finally:
        client.app.dependency_overrides[dependency_spotify_client] = (
            lambda: stub_spotify
        )
