from __future__ import annotations

from app.api.router_registry import compose_prefix, get_domain_routers
from app.api.spotify import router as spotify_domain_router
from app.api.routers import search as search_domain_module
from app.api.routers import system as system_domain_module
from app.api.routers import watchlist as watchlist_domain_module
from app.routers import (
    activity_router,
    download_router,
    dlq_router,
    health_router,
    imports_router,
    integrations_router,
    matching_router,
    metadata_router,
    settings_router,
    soulseek_router,
    sync_router,
)


def test_compose_prefix_normalises_slashes() -> None:
    assert compose_prefix("/api/v1", "spotify", "/free") == "/api/v1/spotify/free"
    assert compose_prefix("/api/v1/", "/spotify//", "free/") == "/api/v1/spotify/free"


def test_compose_prefix_handles_empty_segments() -> None:
    assert compose_prefix("", "", "") == ""
    assert compose_prefix("/", "") == "/"
    assert compose_prefix("/base", "") == "/base"
    assert compose_prefix("", "/nested/path/") == "/nested/path"


def test_get_domain_routers_matches_expected_configuration() -> None:
    expected = [
        ("", spotify_domain_router, []),
        ("", imports_router, []),
        ("/soulseek", soulseek_router, ["Soulseek"]),
        ("/matching", matching_router, ["Matching"]),
        ("/settings", settings_router, ["Settings"]),
        ("", metadata_router, []),
        ("/dlq", dlq_router, ["DLQ"]),
        ("", sync_router, []),
        ("", system_domain_module.router, ["System"]),
        ("", download_router, []),
        ("", activity_router, []),
        ("", integrations_router, []),
        ("/health", health_router, ["Health"]),
        ("", watchlist_domain_module.router, ["Watchlist"]),
        ("", search_domain_module.router, ["Search"]),
    ]

    assert get_domain_routers() == expected

    first_call = get_domain_routers()
    first_call[0][2].append("Extra")
    assert get_domain_routers()[0][2] == []
