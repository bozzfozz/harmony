"""Ensure legacy router modules emit consistent deprecation warnings."""

from __future__ import annotations

import importlib
import re
import sys

import pytest


@pytest.mark.parametrize(
    ("legacy_module", "target"),
    [
        ("app.routers.backfill_router", "app.api.routers.spotify.backfill_router"),
        (
            "app.routers.free_ingest_router",
            "app.api.routers.spotify.free_ingest_router",
        ),
        ("app.routers.search_router", "app.api.routers.search.router"),
        ("app.routers.spotify_free_router", "app.api.routers.spotify.free_router"),
        ("app.routers.spotify_router", "app.api.routers.spotify.core_router"),
        ("app.routers.system_router", "app.api.routers.system.router"),
        ("app.routers.watchlist_router", "app.api.routers.watchlist.router"),
    ],
)
def test_legacy_router_shim_emits_warning_and_reexports(
    legacy_module: str, target: str
) -> None:
    """Importing a legacy router triggers a warning and re-exports the new router."""

    sys.modules.pop(legacy_module, None)
    warning_pattern = re.escape(f"{legacy_module} is deprecated; use {target}")

    with pytest.deprecated_call(match=warning_pattern):
        shim = importlib.import_module(legacy_module)

    target_module_path, target_attr = target.rsplit(".", 1)
    target_module = importlib.import_module(target_module_path)

    assert shim.router is getattr(target_module, target_attr)
