"""Entry point for the Harmony FastAPI application."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import sys
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

if sys.version_info < (3, 11):  # pragma: no cover - Python <3.11 fallback

    class ExceptionGroup(Exception):  # type: ignore[override]
        """Compatibility stub for Python versions without ExceptionGroup."""


from app.api.router_registry import compose_prefix as build_router_prefix, get_domain_routers
from app.config import AppConfig, SecurityConfig
from app.core.config import DEFAULT_SETTINGS
from app.dependencies import get_app_config, get_soulseek_client, get_spotify_client, require_api_key
from app.db import get_session, init_db
from app.logging import configure_logging, get_logger
from app.logging_events import log_event
from app.errors import (
    AppError,
    ErrorCode,
    InternalServerError,
    rate_limit_meta,
    to_response,
)
from app.services.health import DependencyStatus, HealthService
from app.services.secret_validation import SecretValidationService
from app.middleware.cache_conditional import CachePolicy, ConditionalCacheMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.services.cache import ResponseCache
from app.utils.activity import activity_manager
from app.utils.settings_store import ensure_default_settings
from app.orchestrator.bootstrap import OrchestratorRuntime, bootstrap_orchestrator
from app.workers import ArtworkWorker, LyricsWorker, MetadataWorker

logger = get_logger(__name__)
_APP_START_TIME = datetime.now(timezone.utc)


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


def _mount_domain_routers(
    router: APIRouter,
    *,
    base_prefix: str,
    emit_log: bool,
) -> None:
    start_time = perf_counter()
    entries = get_domain_routers()
    registered_prefixes: list[str] = []

    for prefix, domain_router, tags in entries:
        if prefix and tags:
            router.include_router(domain_router, prefix=prefix, tags=tags)
        elif prefix:
            router.include_router(domain_router, prefix=prefix)
        elif tags:
            router.include_router(domain_router, tags=tags)
        else:
            router.include_router(domain_router)

        effective_prefix = prefix or domain_router.prefix or ""
        combined_prefix = build_router_prefix(base_prefix, effective_prefix)
        registered_prefixes.append(combined_prefix or "/")

    if emit_log:
        duration_ms = (perf_counter() - start_time) * 1_000
        preview = registered_prefixes[:5]
        if len(registered_prefixes) > 5:
            preview = preview + ["…"]
        logger.info(
            "Mounted %d domain routers",
            len(entries),
            extra={
                "event": "router_registry.mounted",
                "count": len(entries),
                "prefixes": preview,
                "duration_ms": round(duration_ms, 3),
            },
        )


def _initial_orchestrator_status(*, artwork_enabled: bool, lyrics_enabled: bool) -> dict[str, Any]:
    return {
        "enabled_jobs": {
            "sync": True,
            "matching": True,
            "retry": True,
            "watchlist": True,
            "artwork": artwork_enabled,
            "lyrics": lyrics_enabled,
        },
        "scheduler_running": False,
        "dispatcher_running": False,
        "scheduler_expected": False,
        "dispatcher_expected": False,
    }


def _ensure_orchestrator_status(app: FastAPI) -> dict[str, Any]:
    status = getattr(app.state, "orchestrator_status", None)
    if status is None:
        feature_flags = getattr(app.state, "feature_flags", _config_snapshot.features)
        status = _initial_orchestrator_status(
            artwork_enabled=getattr(feature_flags, "enable_artwork", False),
            lyrics_enabled=getattr(feature_flags, "enable_lyrics", False),
        )
        app.state.orchestrator_status = status
    return status


def _orchestrator_component_probe(component: str) -> Callable[[], DependencyStatus]:
    def _probe() -> DependencyStatus:
        status = getattr(app.state, "orchestrator_status", None)
        if status is None:
            return DependencyStatus(ok=False, status="unknown")

        if component == "scheduler":
            expected = status.get("scheduler_expected", True)
            if not expected:
                return DependencyStatus(ok=True, status="disabled")
            running = bool(status.get("scheduler_running"))
            return DependencyStatus(ok=running, status="up" if running else "down")
        if component == "dispatcher":
            expected = status.get("dispatcher_expected", True)
            if not expected:
                return DependencyStatus(ok=True, status="disabled")
            running = bool(status.get("dispatcher_running"))
            return DependencyStatus(ok=running, status="up" if running else "down")

        enabled_jobs = status.get("enabled_jobs", {})
        enabled = enabled_jobs.get(component)
        if enabled is None:
            return DependencyStatus(ok=False, status="unknown")
        return DependencyStatus(ok=True, status="enabled" if enabled else "disabled")

    return _probe


def _build_orchestrator_dependency_probes() -> Mapping[str, Callable[[], DependencyStatus]]:
    jobs = ("sync", "matching", "retry", "watchlist", "artwork", "lyrics")
    probes: dict[str, Callable[[], DependencyStatus]] = {
        "orchestrator:scheduler": _orchestrator_component_probe("scheduler"),
        "orchestrator:dispatcher": _orchestrator_component_probe("dispatcher"),
    }
    for job in jobs:
        probes[f"orchestrator:job:{job}"] = _orchestrator_component_probe(job)
    return probes


_config_snapshot = get_app_config()
_API_BASE_PATH = _config_snapshot.api_base_path
_LEGACY_ROUTES_ENABLED = _config_snapshot.features.enable_legacy_routes


def _apply_security_dependencies(app: FastAPI, security: SecurityConfig) -> None:
    app.state.security_config = security
    app.openapi_schema = None


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


def _resolve_visibility_timeout(raw_value: str | None) -> int:
    resolved = _env_as_int(raw_value, default=60)
    return max(5, resolved)


def _configure_application(config: AppConfig) -> None:
    configure_logging(config.logging.level)
    init_db()
    ensure_default_settings(DEFAULT_SETTINGS)
    logger.info("Database initialised")
    activity_manager.refresh_cache()


def _emit_worker_config_event(config: AppConfig, *, workers_enabled: bool) -> None:
    watchlist_config = config.watchlist
    interval_seconds = _resolve_watchlist_interval(os.getenv("WATCHLIST_INTERVAL"))
    visibility_timeout = _resolve_visibility_timeout(os.getenv("WORKER_VISIBILITY_TIMEOUT_S"))

    meta = {
        "watchlist": {
            "interval_s": interval_seconds,
            "concurrency": watchlist_config.max_concurrency,
            "max_per_tick": watchlist_config.max_per_tick,
            "retry_budget_per_artist": watchlist_config.retry_budget_per_artist,
            "backoff_base_ms": watchlist_config.backoff_base_ms,
            "jitter_pct": watchlist_config.jitter_pct,
        },
        "queue": {
            "visibility_timeout_s": visibility_timeout,
        },
        "providers": {
            "max_concurrency": config.integrations.max_concurrency,
            "slskd": {
                "timeout_ms": config.soulseek.timeout_ms,
                "retry_max": config.soulseek.retry_max,
                "retry_backoff_base_ms": config.soulseek.retry_backoff_base_ms,
                "jitter_pct": config.soulseek.retry_jitter_pct,
            },
        },
        "features": {
            "require_auth": config.security.require_auth,
            "rate_limiting": config.security.rate_limiting_enabled,
            "workers_disabled": not workers_enabled,
        },
    }

    log_event(
        logger,
        "worker.config",
        component="bootstrap",
        status="ok",
        meta=meta,
    )


async def _start_orchestrator_workers(
    app: FastAPI,
    config: AppConfig,
    *,
    enable_artwork: bool,
    enable_lyrics: bool,
) -> dict[str, bool]:
    """Initialise orchestrator components and optional media workers."""

    spotify_client = get_spotify_client()
    soulseek_client = get_soulseek_client()

    state = app.state
    orchestrator_status = _ensure_orchestrator_status(app)
    worker_status: dict[str, bool] = {
        "artwork": False,
        "lyrics": False,
        "metadata": False,
        "orchestrator_scheduler": False,
        "orchestrator_dispatcher": False,
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
    orchestrator_status["enabled_jobs"]["artwork"] = bool(state.artwork_worker)

    state.lyrics_worker = None
    if enable_lyrics:
        state.lyrics_worker = LyricsWorker(spotify_client=spotify_client)
        await state.lyrics_worker.start()
        worker_status["lyrics"] = True
    orchestrator_status["enabled_jobs"]["lyrics"] = bool(state.lyrics_worker)

    state.rich_metadata_worker = MetadataWorker(spotify_client=spotify_client)
    await state.rich_metadata_worker.start()
    worker_status["metadata"] = True

    orchestrator = bootstrap_orchestrator(
        metadata_service=state.rich_metadata_worker,
        artwork_service=state.artwork_worker,
        lyrics_service=state.lyrics_worker,
    )
    state.orchestrator_runtime = orchestrator
    state.orchestrator_stop_event = asyncio.Event()
    state.orchestrator_tasks = [
        asyncio.create_task(orchestrator.scheduler.run(state.orchestrator_stop_event)),
        asyncio.create_task(orchestrator.dispatcher.run(state.orchestrator_stop_event)),
    ]
    worker_status["orchestrator_scheduler"] = True
    worker_status["orchestrator_dispatcher"] = True
    orchestrator_status["scheduler_running"] = True
    orchestrator_status["dispatcher_running"] = True
    orchestrator_status["scheduler_expected"] = True
    orchestrator_status["dispatcher_expected"] = True
    for job_type, enabled in orchestrator.enabled_jobs.items():
        orchestrator_status["enabled_jobs"][job_type] = bool(enabled)

    return worker_status


async def _start_background_workers(
    app: FastAPI,
    config: AppConfig,
    *,
    enable_artwork: bool,
    enable_lyrics: bool,
) -> dict[str, bool]:  # pragma: no cover - compatibility shim
    """Compatibility wrapper forwarding to orchestrator worker startup."""

    return await _start_orchestrator_workers(
        app,
        config,
        enable_artwork=enable_artwork,
        enable_lyrics=enable_lyrics,
    )


async def _stop_worker(worker: Any) -> None:
    if worker is None:
        return
    stop = getattr(worker, "stop", None)
    if not callable(stop):
        return
    result = stop()
    if inspect.isawaitable(result):
        await result


async def _stop_orchestrator_workers(app: FastAPI) -> None:
    state = app.state
    orchestrator_status = getattr(state, "orchestrator_status", None)

    tasks = list(getattr(state, "orchestrator_tasks", []))
    stop_event: asyncio.Event | None = getattr(state, "orchestrator_stop_event", None)
    runtime: OrchestratorRuntime | None = getattr(state, "orchestrator_runtime", None)

    if runtime is not None:
        runtime.dispatcher.request_stop()
        runtime.scheduler.request_stop()

    if stop_event is not None:
        stop_event.set()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    for attribute in ("orchestrator_tasks", "orchestrator_stop_event", "orchestrator_runtime"):
        if hasattr(state, attribute):
            delattr(state, attribute)

    for attribute in ("artwork_worker", "lyrics_worker", "rich_metadata_worker"):
        await _stop_worker(getattr(state, attribute, None))
        if hasattr(state, attribute):
            delattr(state, attribute)

    if orchestrator_status is not None:
        orchestrator_status["scheduler_running"] = False
        orchestrator_status["dispatcher_running"] = False
        orchestrator_status["scheduler_expected"] = False
        orchestrator_status["dispatcher_expected"] = False
        enabled_jobs = orchestrator_status.get("enabled_jobs", {})
        for job in ("artwork", "lyrics"):
            enabled_jobs[job] = False


async def _stop_background_workers(app: FastAPI) -> None:  # pragma: no cover - compatibility shim
    """Compatibility wrapper forwarding to orchestrator shutdown."""

    await _stop_orchestrator_workers(app)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_app_config()
    _configure_application(config)

    _apply_security_dependencies(app, config.security)

    workers_enabled = _should_start_workers()
    _emit_worker_config_event(config, workers_enabled=workers_enabled)

    feature_flags = config.features
    app.state.feature_flags = feature_flags
    app.state.api_base_path = config.api_base_path
    app.state.legacy_routes_enabled = feature_flags.enable_legacy_routes
    orchestrator_status = _ensure_orchestrator_status(app)

    enable_artwork = feature_flags.enable_artwork
    enable_lyrics = feature_flags.enable_lyrics
    legacy_routes_enabled = feature_flags.enable_legacy_routes

    enabled_jobs = orchestrator_status.setdefault("enabled_jobs", {})
    enabled_jobs.update(
        {
            "sync": True,
            "matching": True,
            "retry": True,
            "watchlist": True,
            "artwork": enable_artwork,
            "lyrics": enable_lyrics,
        }
    )
    orchestrator_status["scheduler_running"] = False
    orchestrator_status["dispatcher_running"] = False
    orchestrator_status["scheduler_expected"] = workers_enabled
    orchestrator_status["dispatcher_expected"] = workers_enabled

    worker_status: dict[str, bool] = {}

    if workers_enabled:
        worker_status = await _start_orchestrator_workers(
            app,
            config,
            enable_artwork=enable_artwork,
            enable_lyrics=enable_lyrics,
        )
    else:
        logger.info("Background workers disabled via HARMONY_DISABLE_WORKERS")
        worker_status = {
            "artwork": False,
            "lyrics": False,
            "metadata": False,
            "orchestrator_scheduler": False,
            "orchestrator_dispatcher": False,
        }

    router_status = {
        "spotify": True,
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

    orchestrator_jobs = dict(orchestrator_status.get("enabled_jobs", {}))

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
            "orchestrator_jobs": orchestrator_jobs,
            "orchestrator_components": {
                "scheduler": orchestrator_status.get("scheduler_running", False),
                "dispatcher": orchestrator_status.get("dispatcher_running", False),
            },
        },
    )

    logger.info("Harmony application started")
    try:
        yield
    finally:
        await _stop_orchestrator_workers(app)
        logger.info("Harmony application stopped")


_docs_url = _compose_subpath(_API_BASE_PATH, "/docs")
_redoc_url = _compose_subpath(_API_BASE_PATH, "/redoc")
_openapi_url = _compose_subpath(_API_BASE_PATH, "/openapi.json")

app = FastAPI(
    title="Harmony Backend",
    version="1.4.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

_apply_security_dependencies(app, _config_snapshot.security)

app.state.start_time = _APP_START_TIME
app.state.orchestrator_status = _initial_orchestrator_status(
    artwork_enabled=_config_snapshot.features.enable_artwork,
    lyrics_enabled=_config_snapshot.features.enable_lyrics,
)
app.state.health_service = HealthService(
    start_time=_APP_START_TIME,
    version=app.version,
    config=_config_snapshot.health,
    session_factory=get_session,
    dependency_probes=_build_orchestrator_dependency_probes(),
)
app.state.secret_validation_service = SecretValidationService()

_initial_security = _config_snapshot.security

app.add_middleware(RequestIDMiddleware)

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
    vary_headers=("Authorization", "X-API-Key", "Origin", "Accept-Encoding"),
)


@app.middleware("http")
async def enforce_api_key(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    security_config = getattr(request.app.state, "security_config", _config_snapshot.security)
    if security_config.require_auth:
        try:
            require_api_key(request)
        except AppError as exc:
            return exc.as_response(request_path=request.url.path, method=request.method)
    return await call_next(request)


async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


_api_base_prefix = _format_router_prefix(_API_BASE_PATH)

_versioned_router = APIRouter()
_mount_domain_routers(
    _versioned_router,
    base_prefix=_api_base_prefix,
    emit_log=True,
)
_versioned_router.add_api_route("/", root, methods=["GET"], tags=["System"])
app.include_router(_versioned_router, prefix=_api_base_prefix)

if _LEGACY_ROUTES_ENABLED:
    legacy_router = APIRouter(route_class=LegacyLoggingRoute)
    _mount_domain_routers(legacy_router, base_prefix="", emit_log=False)
    legacy_router.add_api_route("/", root, methods=["GET"], tags=["System"])
    app.include_router(legacy_router)


def _format_validation_field(raw_loc: list[Any]) -> str:
    location: list[str] = [str(part) for part in raw_loc]
    if location and location[0] in {"body", "query", "path", "header", "cookie"}:
        location = location[1:]
    return ".".join(location) if location else ""


def _extract_detail_message(detail: Any, default: str) -> str:
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, Mapping):
        for key in ("message", "detail", "error"):
            candidate = detail.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    return default


def _extract_detail_meta(detail: Any) -> Mapping[str, Any] | None:
    if isinstance(detail, Mapping):
        candidate = detail.get("meta")
        if isinstance(candidate, Mapping):
            return candidate
        extras = {k: v for k, v in detail.items() if k not in {"message", "detail", "error"}}
        if extras:
            return extras
    return None


@app.exception_handler(RequestValidationError)
async def handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields: list[dict[str, str]] = []
    for error in exc.errors():
        raw_loc = error.get("loc", [])
        if isinstance(raw_loc, (list, tuple)):
            components = list(raw_loc)
        else:
            components = [raw_loc]
        location = _format_validation_field(components)
        if not location:
            location = ".".join(str(component) for component in components if component is not None)
        message = error.get("msg", "Invalid input.")
        fields.append({"name": location or "?", "message": message})
    meta = {"fields": fields} if fields else None
    return to_response(
        message="Request validation failed.",
        code=ErrorCode.VALIDATION_ERROR,
        status_code=status.HTTP_400_BAD_REQUEST,
        request_path=request.url.path,
        method=request.method,
        meta=meta,
    )


async def _render_http_exception(
    request: Request,
    *,
    status_code: int,
    detail: Any,
    headers: Mapping[str, str] | None,
) -> JSONResponse:
    effective_status = status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
    header_map = dict(headers or {})

    if effective_status == status.HTTP_404_NOT_FOUND:
        message = _extract_detail_message(detail, "Resource not found.")
        return to_response(
            message=message,
            code=ErrorCode.NOT_FOUND,
            status_code=effective_status,
            request_path=request.url.path,
            method=request.method,
            headers=header_map or None,
        )

    if effective_status == status.HTTP_429_TOO_MANY_REQUESTS:
        message = _extract_detail_message(detail, "Too many requests.")
        base_meta = _extract_detail_meta(detail)
        meta, retry_headers = rate_limit_meta(header_map)
        if base_meta:
            meta = {**base_meta, **(meta or {})}
        combined_headers = {**header_map, **retry_headers}
        return to_response(
            message=message,
            code=ErrorCode.RATE_LIMITED,
            status_code=effective_status,
            request_path=request.url.path,
            method=request.method,
            meta=meta,
            headers=combined_headers or None,
        )

    if effective_status in {424, 502, 503, 504}:
        message = _extract_detail_message(detail, "Upstream service is unavailable.")
        meta = _extract_detail_meta(detail)
        return to_response(
            message=message,
            code=ErrorCode.DEPENDENCY_ERROR,
            status_code=effective_status,
            request_path=request.url.path,
            method=request.method,
            meta=meta,
            headers=header_map or None,
        )

    if effective_status == status.HTTP_400_BAD_REQUEST:
        message = _extract_detail_message(detail, "Request validation failed.")
        meta = _extract_detail_meta(detail)
        return to_response(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=effective_status,
            request_path=request.url.path,
            method=request.method,
            meta=meta,
            headers=header_map or None,
        )

    if effective_status >= 500:
        message = _extract_detail_message(detail, "An unexpected error occurred.")
        meta = _extract_detail_meta(detail)
        return to_response(
            message=message,
            code=ErrorCode.INTERNAL_ERROR,
            status_code=effective_status,
            request_path=request.url.path,
            method=request.method,
            meta=meta,
        )

    message = _extract_detail_message(detail, "Request could not be completed.")
    meta = _extract_detail_meta(detail)
    return to_response(
        message=message,
        code=ErrorCode.INTERNAL_ERROR,
        status_code=effective_status,
        request_path=request.url.path,
        method=request.method,
        meta=meta,
        headers=header_map or None,
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return await _render_http_exception(
        request,
        status_code=exc.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=exc.detail,
        headers=exc.headers,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_starlette_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return await _render_http_exception(
        request,
        status_code=exc.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=exc.detail,
        headers=exc.headers,
    )


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return exc.as_response(request_path=request.url.path, method=request.method)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error", exc_info=exc)
    error = InternalServerError()
    return error.as_response(request_path=request.url.path, method=request.method)


if sys.version_info >= (3, 11):  # pragma: no branch - version guard

    @app.exception_handler(ExceptionGroup)  # type: ignore[arg-type]
    async def handle_exception_group(request: Request, exc: ExceptionGroup) -> JSONResponse:
        logger.exception("Unhandled application error group", exc_info=exc)
        error = InternalServerError()
        return error.as_response(request_path=request.url.path, method=request.method)


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

    error_object_schema = {
        "type": "object",
        "required": ["code", "message"],
        "properties": {
            "code": {
                "type": "string",
                "enum": [
                    "VALIDATION_ERROR",
                    "NOT_FOUND",
                    "RATE_LIMITED",
                    "DEPENDENCY_ERROR",
                    "INTERNAL_ERROR",
                ],
            },
            "message": {"type": "string"},
            "meta": {"type": "object", "additionalProperties": True},
        },
    }
    error_response_schema = {
        "type": "object",
        "required": ["ok", "error"],
        "properties": {
            "ok": {"type": "boolean", "const": False},
            "error": {"$ref": "#/components/schemas/ErrorObject"},
        },
    }
    schemas_section = components.setdefault("schemas", {})
    schemas_section.setdefault("ErrorObject", error_object_schema)
    schemas_section.setdefault("ErrorResponse", error_response_schema)
    schemas_section.setdefault(
        "HealthData",
        {
            "type": "object",
            "required": ["status", "version", "uptime_s"],
            "properties": {
                "status": {"type": "string", "enum": ["up"]},
                "version": {"type": "string"},
                "uptime_s": {"type": "number"},
            },
        },
    )
    schemas_section.setdefault(
        "HealthResponse",
        {
            "type": "object",
            "required": ["ok", "data", "error"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "data": {"$ref": "#/components/schemas/HealthData"},
                "error": {"type": "null"},
            },
        },
    )
    schemas_section.setdefault(
        "ReadyData",
        {
            "type": "object",
            "required": ["db", "deps"],
            "properties": {
                "db": {"type": "string"},
                "deps": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    )
    schemas_section.setdefault(
        "ReadySuccessResponse",
        {
            "type": "object",
            "required": ["ok", "data", "error"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "data": {"$ref": "#/components/schemas/ReadyData"},
                "error": {"type": "null"},
            },
        },
    )

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
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    error_mappings = {
        "400": "Validation error",
        "404": "Resource not found",
        "429": "Too many requests",
        "424": "Failed dependency",
        "500": "Internal server error",
        "502": "Bad gateway",
        "503": "Service unavailable",
        "504": "Gateway timeout",
    }
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

    for methods in paths.values():
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            for status_code, description in error_mappings.items():
                existing = responses.get(status_code)
                if existing is None:
                    responses[status_code] = {
                        "description": description,
                        "content": {"application/json": {"schema": error_ref}},
                    }
                    continue
                if not isinstance(existing, dict):
                    continue
                existing.setdefault("description", description)
                content = existing.setdefault("content", {})
                content.setdefault("application/json", {"schema": error_ref})

    health_path = _compose_subpath(config.api_base_path, "/health")
    ready_path = _compose_subpath(config.api_base_path, "/ready")
    health_item = paths.get(health_path)
    if isinstance(health_item, dict):
        health_operation = health_item.get("get")
        if isinstance(health_operation, dict):
            health_operation.setdefault("summary", "Liveness probe")
            health_operation.setdefault(
                "description",
                "Returns the service status, version and uptime.",
            )
            responses = health_operation.setdefault("responses", {})
            responses["200"] = {
                "description": "Liveness status",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/HealthResponse"},
                        "example": {
                            "ok": True,
                            "data": {
                                "status": "up",
                                "version": app.version,
                                "uptime_s": 1.23,
                            },
                            "error": None,
                        },
                    }
                },
            }

    ready_item = paths.get(ready_path)
    if isinstance(ready_item, dict):
        ready_operation = ready_item.get("get")
        if isinstance(ready_operation, dict):
            ready_operation.setdefault("summary", "Readiness probe")
            ready_operation.setdefault(
                "description",
                "Checks database connectivity and downstream dependencies.",
            )
            responses = ready_operation.setdefault("responses", {})
            responses["200"] = {
                "description": "All dependencies ready",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ReadySuccessResponse"},
                        "example": {
                            "ok": True,
                            "data": {"db": "up", "deps": {}},
                            "error": None,
                        },
                    }
                },
            }
            responses["503"] = {
                "description": "Dependencies unavailable",
                "content": {
                    "application/json": {
                        "schema": error_ref,
                        "example": {
                            "ok": False,
                            "error": {
                                "code": "DEPENDENCY_ERROR",
                                "message": "not ready",
                                "meta": {
                                    "db": "down",
                                    "deps": {"spotify": "down"},
                                },
                            },
                        },
                    }
                },
            }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
