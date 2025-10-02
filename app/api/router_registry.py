"""Central registry for domain routers exposed by the Harmony API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Iterable, List, Protocol

from fastapi import APIRouter, FastAPI

from app.api.routers import search_router, spotify_router, system_router, watchlist_router
from app.logging import get_logger
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

RouterEntry = tuple[str, APIRouter, list[str]]


@dataclass(frozen=True)
class _Entry:
    prefix: str
    router: APIRouter
    tags: tuple[str, ...] = ()


class _RouterHost(Protocol):
    def include_router(
        self,
        router: APIRouter,
        *,
        prefix: str | None = None,
        tags: list[str] | None = None,
    ) -> None: ...


_DOMAIN_ROUTERS: tuple[_Entry, ...] = (
    _Entry("", spotify_router, ()),
    _Entry("", imports_router, ()),
    _Entry("/soulseek", soulseek_router, ("Soulseek",)),
    _Entry("/matching", matching_router, ("Matching",)),
    _Entry("/settings", settings_router, ("Settings",)),
    _Entry("", metadata_router, ()),
    _Entry("/dlq", dlq_router, ("DLQ",)),
    _Entry("", sync_router, ()),
    _Entry("", system_router, ("System",)),
    _Entry("", download_router, ()),
    _Entry("", activity_router, ()),
    _Entry("", integrations_router, ()),
    _Entry("/health", health_router, ("Health",)),
    _Entry("", watchlist_router, ("Watchlist",)),
    _Entry("", search_router, ("Search",)),
)

_logger = get_logger(__name__)


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


def _entries() -> Iterable[_Entry]:
    return _DOMAIN_ROUTERS


def get_domain_routers() -> list[RouterEntry]:
    """Return the domain routers with their prefixes and tags."""

    return [(entry.prefix, entry.router, list(entry.tags)) for entry in _entries()]


def attach_domain_routers(
    host: _RouterHost,
    *,
    base_prefix: str = "",
    emit_log: bool = False,
    logger: logging.Logger | None = None,
) -> List[str]:
    """Include all domain routers on the given host and return their effective prefixes."""

    effective_base = compose_prefix("", base_prefix)
    prefixes: list[str] = []
    start = perf_counter()
    for entry in _entries():
        include_kwargs: dict[str, object] = {}
        if entry.prefix:
            include_kwargs["prefix"] = entry.prefix
        if entry.tags:
            include_kwargs["tags"] = list(entry.tags)
        host.include_router(entry.router, **include_kwargs)  # type: ignore[arg-type]
        raw_prefix = entry.prefix or entry.router.prefix or ""
        prefixes.append(compose_prefix(effective_base, raw_prefix) or "/")
    if emit_log:
        resolved_logger = logger or _logger
        duration_ms = (perf_counter() - start) * 1_000
        preview = prefixes[:5]
        if len(prefixes) > 5:
            preview = preview + ["…"]
        resolved_logger.info(
            "Mounted %d domain routers",
            len(prefixes),
            extra={
                "event": "router_registry.mounted",
                "count": len(prefixes),
                "prefixes": preview,
                "duration_ms": round(duration_ms, 3),
            },
        )
    return prefixes


def register(
    app: FastAPI,
    *,
    base_path: str = "",
    emit_log: bool = False,
    route_class: type | None = None,
) -> APIRouter:
    """Create a router with all domain routes and mount it on the application."""

    router = APIRouter(route_class=route_class)
    attach_domain_routers(router, base_prefix=base_path, emit_log=emit_log)
    app.include_router(router, prefix=compose_prefix("", base_path))
    return router


__all__ = [
    "RouterEntry",
    "attach_domain_routers",
    "compose_prefix",
    "get_domain_routers",
    "register",
]
