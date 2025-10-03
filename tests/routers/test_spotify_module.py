from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.routers import spotify as spotify_module


def _route_paths(target: APIRouter) -> set[str]:
    return {route.path for route in target.routes if isinstance(route, APIRoute)}


def test_spotify_router_includes_expected_paths() -> None:
    paths = _route_paths(spotify_module.router)
    assert "/spotify/mode" in paths
    assert "/spotify/backfill/run" in paths
    assert "/spotify/import/free" in paths
    assert "/spotify/free/upload" in paths


def test_legacy_router_alias_removed() -> None:
    assert not hasattr(spotify_module, "legacy_router")
