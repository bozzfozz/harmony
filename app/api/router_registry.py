"""Central registry for FastAPI routers used in the Harmony application."""

from __future__ import annotations

from typing import Iterable

from fastapi import APIRouter

from app.api.spotify import router as spotify_domain_router
from app.routers import (
    activity_router,
    download_router,
    dlq_router,
    health_router,
    imports_router,
    integrations_router,
    matching_router,
    metadata_router,
    search_router,
    settings_router,
    soulseek_router,
    sync_router,
    system_router,
    watchlist_router,
)

RouterEntry = tuple[str, APIRouter, list[str]]


def compose_prefix(base: str, *parts: str) -> str:
    """Join path components into a normalised FastAPI router prefix."""

    segments: list[str] = []
    saw_root = False
    for raw_part in (base, *parts):
        if raw_part is None:
            continue
        candidate = raw_part.strip()
        if not candidate:
            continue
        if candidate == "/":
            saw_root = True
            continue
        segments.extend(part for part in candidate.split("/") if part)
    if segments:
        return "/" + "/".join(segments)
    if saw_root:
        return "/"
    return ""


def _build_entries() -> Iterable[RouterEntry]:
    yield "", spotify_domain_router, []
    yield "", imports_router, []
    yield "/soulseek", soulseek_router, ["Soulseek"]
    yield "/matching", matching_router, ["Matching"]
    yield "/settings", settings_router, ["Settings"]
    yield "", metadata_router, []
    yield "/dlq", dlq_router, ["DLQ"]
    yield "", search_router, []
    yield "", sync_router, []
    yield "", system_router, []
    yield "", download_router, []
    yield "", activity_router, []
    yield "", integrations_router, []
    yield "/health", health_router, ["Health"]
    yield "", watchlist_router, []


def get_domain_routers() -> list[RouterEntry]:
    """Return the list of domain routers with their prefixes and tags."""

    return list(_build_entries())


__all__ = ["compose_prefix", "get_domain_routers"]
