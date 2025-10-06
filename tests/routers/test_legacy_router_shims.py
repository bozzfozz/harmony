from __future__ import annotations

import importlib
import re
import sys

import pytest


@pytest.mark.parametrize(
    ("module_name", "replacement"),
    [
        ("app.routers.spotify_router", "app.api.spotify.core_router"),
        ("app.routers.search_router", "app.api.routers.search.router"),
        ("app.routers.spotify_free_router", "app.api.spotify.free_router"),
        ("app.routers.free_ingest_router", "app.api.spotify.free_ingest_router"),
        ("app.routers.watchlist_router", "app.api.routers.watchlist.router"),
        ("app.routers.system_router", "app.api.routers.system.router"),
        ("app.routers.backfill_router", "app.api.spotify.backfill_router"),
    ],
)
def test_importing_legacy_router_modules_emits_deprecation_warning(
    module_name: str, replacement: str
) -> None:
    sys.modules.pop(module_name, None)
    try:
        with pytest.deprecated_call(match=re.escape(replacement)):
            importlib.import_module(module_name)
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.parametrize(
    ("attribute", "module_path", "replacement"),
    [
        ("search_router", "app.api.routers.search", "app.api.routers.search.router"),
        ("system_router", "app.api.routers.system", "app.api.routers.system.router"),
        (
            "watchlist_router",
            "app.api.routers.watchlist",
            "app.api.routers.watchlist.router",
        ),
    ],
)
def test_package_level_access_emits_deprecation_warning(
    attribute: str, module_path: str, replacement: str
) -> None:
    package = importlib.import_module("app.routers")
    package.__dict__.pop(attribute, None)

    with pytest.deprecated_call(match=re.escape(replacement)):
        exported = getattr(package, attribute)

    replacement_module = importlib.import_module(module_path)
    assert exported is getattr(replacement_module, "router")
