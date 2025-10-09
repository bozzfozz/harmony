from __future__ import annotations

from app.api import artists, router_registry, search, spotify, system, watchlist
from app.routers import (
    activity_router,
    dlq_router,
    download_router,
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
    assert (
        router_registry.compose_prefix("/api/v1", "spotify", "/free")
        == "/api/v1/spotify/free"
    )
    assert (
        router_registry.compose_prefix("/api/v1/", "/spotify//", "free/")
        == "/api/v1/spotify/free"
    )


def test_compose_prefix_handles_empty_segments() -> None:
    assert router_registry.compose_prefix("", "", "") == ""
    assert router_registry.compose_prefix("/", "") == "/"
    assert router_registry.compose_prefix("/base", "") == "/base"
    assert router_registry.compose_prefix("", "/nested/path/") == "/nested/path"


def test_domain_router_metadata_is_registered_in_order() -> None:
    entries = list(router_registry.iter_domain_routers())
    keys = [entry.key for entry in entries]
    assert keys == ["spotify", "artists", "system", "watchlist", "search"]

    lookup = {entry.key: entry for entry in entries}
    assert lookup["spotify"].router is spotify.router
    assert lookup["artists"].router is artists.router
    assert lookup["system"].router is system.router
    assert lookup["watchlist"].router is watchlist.router
    assert lookup["search"].router is search.router

    expected_tags = {
        "spotify": (),
        "artists": ("Artists",),
        "system": (),
        "watchlist": (),
        "search": (),
    }
    for entry in entries:
        assert entry.base == "/api/v1"
        assert entry.tags == expected_tags[entry.key]


def test_full_registry_matches_expected_configuration() -> None:
    entries = list(router_registry.iter_registered_routers())
    keys = [entry.key for entry in entries]
    assert keys == [
        "spotify",
        "artists",
        "imports",
        "soulseek",
        "matching",
        "settings",
        "metadata",
        "dlq",
        "sync",
        "system",
        "download",
        "activity",
        "spotify_free_links",
        "integrations",
        "health",
        "watchlist",
        "search",
    ]

    lookup = {entry.key: entry for entry in entries}
    assert lookup["artists"].router is artists.router
    assert lookup["imports"].router is imports_router
    assert lookup["soulseek"].router is soulseek_router
    assert lookup["matching"].router is matching_router
    assert lookup["settings"].router is settings_router
    assert lookup["metadata"].router is metadata_router
    assert lookup["dlq"].router is dlq_router
    assert lookup["sync"].router is sync_router
    assert lookup["download"].router is download_router
    assert lookup["activity"].router is activity_router
    assert lookup["integrations"].router is integrations_router
    assert lookup["health"].router is health_router
    assert lookup["soulseek"].prefix == "/soulseek"
    assert lookup["matching"].tags == ("Matching",)
    assert lookup["health"].prefix == "/health"
    assert lookup["search"].tags == ()
