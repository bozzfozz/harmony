from __future__ import annotations

from fastapi import FastAPI

from app.api.spotify import (
    backfill_router,
    core_router,
    free_ingest_router,
    free_router,
    router as spotify_router,
)


def _collect_paths(app_router) -> set[tuple[str, frozenset[str]]]:
    paths: set[tuple[str, frozenset[str]]] = set()
    for route in app_router.routes:
        methods = frozenset(route.methods or [])
        paths.add((route.path, methods))
    return paths


def test_unified_router_includes_all_sections() -> None:
    app = FastAPI()
    app.include_router(spotify_router)

    paths = _collect_paths(app.router)

    expected = {
        ("/spotify/status", frozenset({"GET"})),
        ("/spotify/import/free", frozenset({"POST"})),
        ("/spotify/backfill/run", frozenset({"POST"})),
        ("/spotify/free/upload", frozenset({"POST"})),
    }
    for item in expected:
        assert item in paths, f"Expected route {item} to be registered"


def test_section_routers_share_registration_contract() -> None:
    core_paths = _collect_paths(core_router)
    assert ("/spotify/status", frozenset({"GET"})) in core_paths

    backfill_paths = _collect_paths(backfill_router)
    assert ("/spotify/backfill/run", frozenset({"POST"})) in backfill_paths

    free_ingest_paths = _collect_paths(free_ingest_router)
    assert ("/spotify/import/free", frozenset({"POST"})) in free_ingest_paths

    free_paths = _collect_paths(free_router)
    assert ("/spotify/free/upload", frozenset({"POST"})) in free_paths
