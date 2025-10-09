from __future__ import annotations

import importlib

import pytest
from tests.utils.openapi import openapi_flag_context

from app.main import app


def _collect_tags(schema: dict[str, object]) -> tuple[str, ...]:
    paths = schema.get("paths", {})
    collected: set[str] = set()
    if isinstance(paths, dict):
        for operations in paths.values():
            if not isinstance(operations, dict):
                continue
            for operation in operations.values():
                if not isinstance(operation, dict):
                    continue
                tags = operation.get("tags", [])
                if isinstance(tags, list):
                    for tag in tags:
                        if isinstance(tag, str):
                            collected.add(tag)
    return tuple(sorted(collected))


def test_openapi_sorting_is_stable_across_runs() -> None:
    app.openapi_schema = None
    first = app.openapi()
    app.openapi_schema = None
    second = app.openapi()

    assert first == second
    first_hash = first.get("info", {}).get("x-schema-hash")
    second_hash = second.get("info", {}).get("x-schema-hash")
    assert first_hash == second_hash


def test_openapi_respects_feature_flag_context() -> None:
    app.openapi_schema = None
    base_paths = set(app.openapi().get("paths", {}))
    target_path = "/admin/artists/{artist_key}/reconcile"
    assert target_path not in base_paths

    with openapi_flag_context(enable_admin_api=True):
        schema = app.openapi()
        assert target_path in schema.get("paths", {})

    app.openapi_schema = None
    restored_paths = set(app.openapi().get("paths", {}))
    assert target_path not in restored_paths


def test_legacy_shims_do_not_pollute_tags() -> None:
    app.openapi_schema = None
    baseline_tags = _collect_tags(app.openapi())

    with pytest.warns(DeprecationWarning):
        importlib.import_module("app.routers.search_router")
    with pytest.warns(DeprecationWarning):
        importlib.import_module("app.routers.system_router")
    with pytest.warns(DeprecationWarning):
        importlib.import_module("app.routers.watchlist_router")

    app.openapi_schema = None
    shim_tags = _collect_tags(app.openapi())
    assert shim_tags == baseline_tags
