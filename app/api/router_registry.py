"""Central registry for Harmony FastAPI routers."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import perf_counter
from typing import Iterator, Sequence

from fastapi import APIRouter, FastAPI

from app.logging import get_logger

__all__ = [
    "RouterConfig",
    "compose_prefix",
    "iter_domain_routers",
    "iter_registered_routers",
    "register_all",
    "register_domain",
    "register_router",
]


@dataclass(frozen=True)
class RouterConfig:
    """Configuration describing how a router should be exposed."""

    key: str
    router: APIRouter
    prefix: str
    tags: tuple[str, ...]
    base: str
    kind: str


_registry: "OrderedDict[str, RouterConfig]" = OrderedDict()
_logger = get_logger(__name__)
_DEFAULT_BASE = "/api/v1"


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


def _register(entry: RouterConfig) -> RouterConfig:
    if entry.key in _registry:
        raise ValueError(f"Router '{entry.key}' is already registered")
    if not entry.router.routes:
        raise ValueError(f"Router '{entry.key}' does not expose any routes")
    _registry[entry.key] = entry
    return entry


def register_domain(
    key: str,
    router: APIRouter,
    *,
    base: str = _DEFAULT_BASE,
    prefix: str | None = None,
    tags: Sequence[str] | None = None,
) -> RouterConfig:
    """Register a domain router that should live under the API base path."""

    resolved_prefix = prefix if prefix is not None else router.prefix or ""
    resolved_tags: tuple[str, ...]
    if tags is None:
        inferred = list(router.tags or [])
        if not inferred:
            inferred = [key.replace("_", " ").title()]
        resolved_tags = tuple(inferred)
    else:
        resolved_tags = tuple(tags)
    entry = RouterConfig(
        key=key,
        router=router,
        prefix=resolved_prefix,
        tags=resolved_tags,
        base=base,
        kind="domain",
    )
    return _register(entry)


def register_router(
    key: str,
    router: APIRouter,
    *,
    prefix: str = "",
    tags: Sequence[str] | None = None,
    base: str = _DEFAULT_BASE,
    kind: str = "shared",
) -> RouterConfig:
    """Register an additional router that participates in the registry."""

    resolved_tags = tuple(tags or router.tags or ())
    entry = RouterConfig(
        key=key,
        router=router,
        prefix=prefix,
        tags=resolved_tags,
        base=base,
        kind=kind,
    )
    return _register(entry)


def iter_registered_routers() -> Iterator[RouterConfig]:
    """Yield all registered routers in registration order."""

    return iter(_registry.values())


def iter_domain_routers() -> Iterator[RouterConfig]:
    """Yield only routers registered as domain routers."""

    return (entry for entry in _registry.values() if entry.kind == "domain")


def register_all(
    app: FastAPI,
    *,
    base_path: str | None = None,
    emit_log: bool = False,
    route_class: type | None = None,
    router: APIRouter | None = None,
) -> APIRouter:
    """Include all registered routers on the FastAPI application."""

    aggregator = router or APIRouter(route_class=route_class)
    start = perf_counter()
    for entry in _registry.values():
        include_kwargs: dict[str, object] = {}
        if entry.prefix:
            include_kwargs["prefix"] = entry.prefix
        if entry.tags:
            include_kwargs["tags"] = list(entry.tags)
        aggregator.include_router(entry.router, **include_kwargs)  # type: ignore[arg-type]
    effective_base = base_path if base_path is not None else _DEFAULT_BASE
    app.include_router(aggregator, prefix=compose_prefix("", effective_base))
    if emit_log:
        duration_ms = (perf_counter() - start) * 1_000
        preview = [
            compose_prefix(effective_base, entry.prefix) or "/"
            for entry in _registry.values()
        ][:5]
        if len(_registry) > 5:
            preview.append("…")
        _logger.info(
            "Mounted %d routers",
            len(_registry),
            extra={
                "event": "router_registry.mounted",
                "count": len(_registry),
                "prefixes": preview,
                "duration_ms": round(duration_ms, 3),
            },
        )
    return aggregator


# ---------------------------------------------------------------------------
# Built-in router registrations
# ---------------------------------------------------------------------------

from app.api import (  # noqa: E402
    artists,
    search,
    spotify,
    spotify_free_links,
    system,
    watchlist,
)
from app.routers import (  # noqa: E402
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

register_domain("spotify", spotify.router, tags=())
register_domain("artists", artists.router, prefix="")
register_router("imports", imports_router)
register_router("soulseek", soulseek_router, prefix="/soulseek", tags=("Soulseek",))
register_router("matching", matching_router, prefix="/matching", tags=("Matching",))
register_router("settings", settings_router, prefix="/settings", tags=("Settings",))
register_router("metadata", metadata_router)
register_router("dlq", dlq_router, prefix="/dlq", tags=("DLQ",))
register_router("sync", sync_router)
register_domain("system", system.router, tags=())
register_router("download", download_router)
register_router("activity", activity_router)
register_router("spotify_free_links", spotify_free_links.router)
register_router("integrations", integrations_router)
register_router("health", health_router, prefix="/health", tags=("Health",))
register_domain("watchlist", watchlist.router, prefix="", tags=())
register_domain("search", search.router, prefix="", tags=())
