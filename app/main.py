"""Entry point for the Harmony FastAPI application."""

from __future__ import annotations

import inspect
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.config import AppConfig
from app.core.config import DEFAULT_SETTINGS
from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_soulseek_client,
    get_spotify_client,
    require_api_key,
)
from app.db import init_db
from app.logging import configure_logging, get_logger
from app.routers import (
    activity_router,
    backfill_router,
    download_router,
    free_ingest_router,
    health_router,
    integrations_router,
    imports_router,
    matching_router,
    metadata_router,
    search_router,
    settings_router,
    soulseek_router,
    spotify_free_router,
    spotify_router,
    sync_router,
    system_router,
    watchlist_router,
)
from app.services.backfill_service import BackfillService
from app.middleware.cache_conditional import CachePolicy, ConditionalCacheMiddleware
from app.services.cache import ResponseCache
from app.problem_details import ProblemDetailException
from app.utils.activity import activity_manager
from app.utils.settings_store import ensure_default_settings
from app.workers import (
    ArtworkWorker,
    BackfillWorker,
    LyricsWorker,
    MatchingWorker,
    MetadataWorker,
    PlaylistSyncWorker,
    SyncWorker,
    WatchlistWorker,
)
from app.workers.retry_scheduler import RetryScheduler

logger = get_logger(__name__)


def _compose_subpath(base_path: str, suffix: str) -> str:
    cleaned_suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    if not base_path or base_path == "/":
        return cleaned_suffix
    return f"{base_path.rstrip('/')}{cleaned_suffix}"


def _format_router_prefix(base_path: str) -> str:
    if not base_path or base_path == "/":
        return ""
    return base_path


def _env_as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_as_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalise_cache_path(raw_path: str, base_path: str) -> str:
    path = raw_path.strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path}"
    if not base_path or base_path == "/":
        return path
    if path.startswith(base_path):
        return path
    return f"{base_path.rstrip('/')}{path}"


def _parse_cache_policies(
    raw_value: str | None,
    *,
    base_path: str,
    default_ttl: int,
    default_stale: int,
) -> dict[str, CachePolicy]:
    if not raw_value:
        return {}
    policies: dict[str, CachePolicy] = {}
    for chunk in raw_value.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        parts = [component.strip() for component in entry.split("|") if component.strip()]
        if not parts:
            continue
        path = _normalise_cache_path(parts[0], base_path)
        max_age = default_ttl
        stale = default_stale
        if len(parts) > 1:
            max_age = _env_as_int(parts[1], default=default_ttl)
        if len(parts) > 2:
            stale = _env_as_int(parts[2], default=default_stale)
        policies[path] = CachePolicy(path=path, max_age=max_age, stale_while_revalidate=stale)
    return policies


class LegacyLoggingRoute(APIRoute):
    """Route implementation that records access to legacy API endpoints."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original_handler = super().get_route_handler()

        async def logging_route_handler(request: Request) -> Response:
            response = await original_handler(request)
            logger.info(
                "Legacy API route accessed",
                extra={
                    "event": "api.legacy.hit",
                    "path": request.url.path,
                    "status": response.status_code,
                },
            )
            return response

        return logging_route_handler


def _register_api_routes(
    router: APIRouter,
    root_handler: Callable[[], Awaitable[dict[str, str]]],
) -> None:
    router.include_router(spotify_router, prefix="/spotify", tags=["Spotify"])
    router.include_router(backfill_router, prefix="/spotify/backfill", tags=["Spotify Backfill"])
    router.include_router(spotify_free_router)
    router.include_router(free_ingest_router)
    router.include_router(imports_router)
    router.include_router(soulseek_router, prefix="/soulseek", tags=["Soulseek"])
    router.include_router(matching_router, prefix="/matching", tags=["Matching"])
    router.include_router(settings_router, prefix="/settings", tags=["Settings"])
    router.include_router(metadata_router)
    router.include_router(search_router)
    router.include_router(sync_router)
    router.include_router(system_router)
    router.include_router(download_router)
    router.include_router(activity_router)
    router.include_router(integrations_router)
    router.include_router(health_router, prefix="/health", tags=["Health"])
    router.include_router(watchlist_router)
    router.add_api_route("/", root_handler, methods=["GET"], tags=["System"])


_config_snapshot = get_app_config()
_API_BASE_PATH = _config_snapshot.api_base_path
_LEGACY_ROUTES_ENABLED = _config_snapshot.features.enable_legacy_routes


def _should_start_workers() -> bool:
    return os.getenv("HARMONY_DISABLE_WORKERS") not in {"1", "true", "TRUE"}


def _resolve_watchlist_interval(raw_value: str | None) -> float:
    default = 86_400.0
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid WATCHLIST_INTERVAL value %s; falling back to default",
            raw_value,
        )
        return default


def _configure_application(config: AppConfig) -> None:
    configure_logging(config.logging.level)
    init_db()
    ensure_default_settings(DEFAULT_SETTINGS)
    logger.info("Database initialised")
    activity_manager.refresh_cache()


async def _start_background_workers(
    app: FastAPI,
    config: AppConfig,
    *,
    enable_artwork: bool,
    enable_lyrics: bool,
) -> dict[str, bool]:
    soulseek_client = get_soulseek_client()
    matching_engine = get_matching_engine()
    spotify_client = get_spotify_client()

    state = app.state
    worker_status: dict[str, bool] = {
        "artwork": False,
        "lyrics": False,
        "metadata": False,
        "sync": False,
        "retry_scheduler": False,
        "matching": False,
        "playlist_sync": False,
        "backfill": False,
        "watchlist": False,
    }

    state.artwork_worker = None
    if enable_artwork:
        state.artwork_worker = ArtworkWorker(
            spotify_client=spotify_client,
            soulseek_client=soulseek_client,
            config=config.artwork,
        )
        await state.artwork_worker.start()
        worker_status["artwork"] = True

    state.lyrics_worker = None
    if enable_lyrics:
        state.lyrics_worker = LyricsWorker(spotify_client=spotify_client)
        await state.lyrics_worker.start()
        worker_status["lyrics"] = True

    state.rich_metadata_worker = MetadataWorker(
        spotify_client=spotify_client,
    )
    await state.rich_metadata_worker.start()
    worker_status["metadata"] = True

    state.sync_worker = SyncWorker(
        soulseek_client,
        metadata_worker=state.rich_metadata_worker,
        artwork_worker=state.artwork_worker,
        lyrics_worker=state.lyrics_worker,
    )
    await state.sync_worker.start()
    worker_status["sync"] = True

    state.retry_scheduler = RetryScheduler(state.sync_worker)
    await state.retry_scheduler.start()
    worker_status["retry_scheduler"] = True

    state.matching_worker = MatchingWorker(matching_engine)
    await state.matching_worker.start()
    worker_status["matching"] = True

    state.playlist_worker = PlaylistSyncWorker(spotify_client)
    await state.playlist_worker.start()
    worker_status["playlist_sync"] = True

    state.backfill_service = BackfillService(config.spotify, spotify_client)
    state.backfill_worker = BackfillWorker(state.backfill_service)
    await state.backfill_worker.start()
    worker_status["backfill"] = True

    interval_seconds = _resolve_watchlist_interval(os.getenv("WATCHLIST_INTERVAL"))
    state.watchlist_worker = WatchlistWorker(
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        sync_worker=state.sync_worker,
        interval_seconds=interval_seconds,
    )
    await state.watchlist_worker.start()
    worker_status["watchlist"] = True

    state.metadata_worker = None
    return worker_status


async def _stop_worker(worker: Any) -> None:
    if worker is None:
        return
    stop = getattr(worker, "stop", None)
    if not callable(stop):
        return
    result = stop()
    if inspect.isawaitable(result):
        await result


async def _stop_background_workers(app: FastAPI) -> None:
    state = app.state
    for attribute in [
        "artwork_worker",
        "lyrics_worker",
        "rich_metadata_worker",
        "retry_scheduler",
        "sync_worker",
        "matching_worker",
        "playlist_worker",
        "backfill_worker",
        "watchlist_worker",
        "metadata_worker",
    ]:
        await _stop_worker(getattr(state, attribute, None))
        if hasattr(state, attribute):
            delattr(state, attribute)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_app_config()
    _configure_application(config)

    feature_flags = config.features
    app.state.feature_flags = feature_flags
    app.state.api_base_path = config.api_base_path
    app.state.legacy_routes_enabled = feature_flags.enable_legacy_routes

    enable_artwork = feature_flags.enable_artwork
    enable_lyrics = feature_flags.enable_lyrics
    legacy_routes_enabled = feature_flags.enable_legacy_routes

    worker_status: dict[str, bool] = {}

    if _should_start_workers():
        worker_status = await _start_background_workers(
            app,
            config,
            enable_artwork=enable_artwork,
            enable_lyrics=enable_lyrics,
        )
    else:
        logger.info("Background workers disabled via HARMONY_DISABLE_WORKERS")

    router_status = {
        "spotify": True,
        "spotify_backfill": True,
        "spotify_free": True,
        "free_ingest": True,
        "imports": True,
        "soulseek": True,
        "matching": True,
        "settings": True,
        "metadata": True,
        "search": True,
        "sync": True,
        "system": True,
        "downloads": True,
        "activity": True,
        "health": True,
        "watchlist": True,
        "legacy_alias": legacy_routes_enabled,
    }

    flag_status = {
        "artwork": enable_artwork,
        "lyrics": enable_lyrics,
        "legacy_routes": legacy_routes_enabled,
    }

    enabled_providers = {name: True for name in config.integrations.enabled}
    logger.info(
        "wiring_summary routers=%s workers=%s flags=%s integrations=%s",
        router_status,
        worker_status,
        flag_status,
        enabled_providers,
        extra={
            "event": "wiring_summary",
            "routers": router_status,
            "workers": worker_status,
            "flags": flag_status,
            "integrations": enabled_providers,
            "api_base_path": config.api_base_path,
        },
    )

    logger.info("Harmony application started")
    try:
        yield
    finally:
        await _stop_background_workers(app)
        logger.info("Harmony application stopped")


_docs_url = _compose_subpath(_API_BASE_PATH, "/docs")
_redoc_url = _compose_subpath(_API_BASE_PATH, "/redoc")
_openapi_url = _compose_subpath(_API_BASE_PATH, "/openapi.json")

app = FastAPI(
    title="Harmony Backend",
    version="1.4.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

_initial_security = _config_snapshot.security

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_initial_security.allowed_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Authorization", "Content-Type", "Accept"],
    allow_credentials=False,
    expose_headers=[],
)

_cache_enabled = _env_as_bool(os.getenv("CACHE_ENABLED"), default=True)
_cache_default_ttl = _env_as_int(os.getenv("CACHE_DEFAULT_TTL_S"), default=30)
_cache_default_stale = _env_as_int(
    os.getenv("CACHE_STALE_WHILE_REVALIDATE_S"), default=_cache_default_ttl * 2
)
_cache_max_items = _env_as_int(os.getenv("CACHE_MAX_ITEMS"), default=5_000)
_cache_fail_open = _env_as_bool(os.getenv("CACHE_FAIL_OPEN"), default=True)
_cache_etag_strategy = os.getenv("CACHE_STRATEGY_ETAG", "strong")
_cacheable_paths_raw = os.getenv("CACHEABLE_PATHS")

_cache_policies = _parse_cache_policies(
    _cacheable_paths_raw,
    base_path=_format_router_prefix(_API_BASE_PATH) or "/",
    default_ttl=_cache_default_ttl,
    default_stale=_cache_default_stale,
)
_cache_default_policy = CachePolicy(
    path="*",
    max_age=_cache_default_ttl,
    stale_while_revalidate=_cache_default_stale,
)
_response_cache = ResponseCache(
    max_items=_cache_max_items,
    default_ttl=float(_cache_default_ttl),
    fail_open=_cache_fail_open,
)
app.state.response_cache = _response_cache
app.state.cache_policies = _cache_policies

app.add_middleware(
    ConditionalCacheMiddleware,
    cache=_response_cache,
    enabled=_cache_enabled,
    policies=_cache_policies,
    default_policy=_cache_default_policy,
    etag_strategy=_cache_etag_strategy,
    vary_headers=("Authorization", "X-API-Key", "Accept-Encoding"),
)


async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


_versioned_router = APIRouter()
_register_api_routes(_versioned_router, root)
app.include_router(_versioned_router, prefix=_format_router_prefix(_API_BASE_PATH))

if _LEGACY_ROUTES_ENABLED:
    legacy_router = APIRouter(route_class=LegacyLoggingRoute)
    _register_api_routes(legacy_router, root)
    app.include_router(legacy_router)


@app.exception_handler(ProblemDetailException)
async def handle_problem_detail(request: Request, exc: ProblemDetailException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
        media_type="application/problem+json",
    )


def _is_allowlisted_path(path: str) -> bool:
    security_config = get_app_config().security
    return any(
        prefix
        and (path == prefix or path.startswith(f"{prefix}/"))
        or (prefix == "/" and path == "/")
        for prefix in security_config.allowlist
    )


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )

    config = get_app_config()
    server_url = config.api_base_path or "/"
    if server_url != "/" and not server_url.startswith("/"):
        server_url = f"/{server_url}"
    openapi_schema["servers"] = [{"url": server_url}]

    security_scheme_name = "ApiKeyAuth"
    security_scheme = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Provide the configured API key via the X-API-Key header. Authorization: Bearer is also supported.",
    }

    components = openapi_schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})[security_scheme_name] = security_scheme

    security_config = config.security

    if security_config.require_auth and security_config.api_keys:
        openapi_schema["security"] = [{security_scheme_name: []}]

        for path, methods in openapi_schema.get("paths", {}).items():
            if _is_allowlisted_path(path):
                for operation in methods.values():
                    if isinstance(operation, dict):
                        operation.pop("security", None)
    else:
        openapi_schema["security"] = []

    cache_header_spec = {
        "ETag": {
            "description": "Entity tag identifying the cached representation.",
            "schema": {"type": "string"},
        },
        "Last-Modified": {
            "description": "Timestamp of the last modification in RFC 1123 format.",
            "schema": {"type": "string", "format": "date-time"},
        },
        "Cache-Control": {
            "description": "Cache directives for clients and proxies.",
            "schema": {"type": "string"},
        },
        "Vary": {
            "description": "Headers that affect the cached representation.",
            "schema": {"type": "string"},
        },
    }

    paths = openapi_schema.get("paths", {})
    for methods in paths.values():
        for method, operation in list(methods.items()):
            if method.lower() != "get" or not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            success = responses.get("200")
            if isinstance(success, dict):
                header_section = success.setdefault("headers", {})
                for header_name, header_spec in cache_header_spec.items():
                    header_section.setdefault(header_name, dict(header_spec))
            not_modified = responses.setdefault(
                "304",
                {
                    "description": "Not Modified",
                    "headers": {},
                },
            )
            header_section = not_modified.setdefault("headers", {})
            for header_name in ("ETag", "Last-Modified", "Cache-Control", "Vary"):
                header_section.setdefault(header_name, dict(cache_header_spec[header_name]))

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
