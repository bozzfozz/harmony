from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.routers.spotify import legacy_router, router


def _route_paths(target: APIRouter) -> set[str]:
    return {route.path for route in target.routes if isinstance(route, APIRoute)}


def test_spotify_router_includes_expected_paths() -> None:
    paths = _route_paths(router)
    assert "/spotify/mode" in paths
    assert "/spotify/backfill/run" in paths
    assert "/spotify/import/free" in paths
    assert "/spotify/free/upload" in paths


def test_legacy_router_is_optional_alias() -> None:
    if legacy_router is None:
        assert legacy_router is None
    else:
        assert isinstance(legacy_router, APIRouter)
