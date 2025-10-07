"""Entry point for the Harmony FastAPI application."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import router_registry
from app.config import AppConfig, SecurityConfig, settings
from app.core.config import DEFAULT_SETTINGS
from app.dependencies import (
    get_app_config,
    get_soulseek_client,
    get_spotify_client,
)
from app.db import get_session, init_db
from app.logging import configure_logging, get_logger
from app.logging_events import log_event
from app.middleware import install_middleware
from app.services.health import DependencyStatus, HealthService
from app.services.secret_validation import SecretValidationService
from app.utils.activity import activity_manager
from app.utils.settings_store import ensure_default_settings
from app.orchestrator.bootstrap import OrchestratorRuntime, bootstrap_orchestrator
from app.orchestrator.timer import WatchlistTimer
from app.workers.artwork_worker import ArtworkWorker
from app.workers.lyrics_worker import LyricsWorker
from app.workers.metadata_worker import MetadataWorker, MetadataUpdateWorker

logger = get_logger(__name__)
_APP_START_TIME = datetime.now(timezone.utc)


def _initial_orchestrator_status(*, artwork_enabled: bool, lyrics_enabled: bool) -> dict[str, Any]:
    return {
        "enabled_jobs": {
            "sync": True,
            "matching": True,
            "retry": True,
            "watchlist": True,
            "artist_refresh": True,
            "artist_delta": True,
            "artwork": artwork_enabled,
            "lyrics": lyrics_enabled,
        },
        "scheduler_running": False,
        "dispatcher_running": False,
        "scheduler_expected": False,
        "dispatcher_expected": False,
        "watchlist_timer_running": False,
        "watchlist_timer_expected": False,
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
        if component == "watchlist_timer":
            expected = status.get("watchlist_timer_expected", True)
            if not expected:
                return DependencyStatus(ok=True, status="disabled")
            running = bool(status.get("watchlist_timer_running"))
            return DependencyStatus(ok=running, status="up" if running else "down")

        enabled_jobs = status.get("enabled_jobs", {})
        enabled = enabled_jobs.get(component)
        if enabled is None:
            return DependencyStatus(ok=False, status="unknown")
        return DependencyStatus(ok=True, status="enabled" if enabled else "disabled")

    return _probe


def _build_orchestrator_dependency_probes() -> Mapping[str, Callable[[], DependencyStatus]]:
    jobs = (
        "sync",
        "matching",
        "retry",
        "artist_refresh",
        "artist_delta",
        "watchlist",
        "artwork",
        "lyrics",
    )
    probes: dict[str, Callable[[], DependencyStatus]] = {
        "orchestrator:scheduler": _orchestrator_component_probe("scheduler"),
        "orchestrator:dispatcher": _orchestrator_component_probe("dispatcher"),
        "orchestrator:timer:watchlist": _orchestrator_component_probe("watchlist_timer"),
    }
    for job in jobs:
        probes[f"orchestrator:job:{job}"] = _orchestrator_component_probe(job)
    return probes


_config_snapshot = get_app_config()
_API_BASE_PATH = _config_snapshot.api_base_path


def _apply_security_dependencies(app: FastAPI, security: SecurityConfig) -> None:
    app.state.security_config = security
    app.openapi_schema = None


def _should_start_workers(*, config: AppConfig | None = None) -> bool:
    resolved_config = config or get_app_config()
    worker_env = resolved_config.environment.workers
    if worker_env.enabled_override is not None:
        return worker_env.enabled_override
    if worker_env.disable_workers:
        return False
    return settings.orchestrator.workers_enabled


def _resolve_watchlist_interval(override: float | None) -> float:
    default = 86_400.0
    if override is None:
        return default
    return override


def _resolve_visibility_timeout(override: int | None) -> int:
    resolved = override if override is not None else settings.orchestrator.visibility_timeout_s
    return max(5, resolved)


def _configure_application(config: AppConfig) -> None:
    configure_logging(config.logging.level)
    init_db()
    ensure_default_settings(DEFAULT_SETTINGS)
    logger.info("Database initialised")
    activity_manager.refresh_cache()


def _emit_worker_config_event(config: AppConfig, *, workers_enabled: bool) -> None:
    watchlist_config = config.watchlist
    worker_env = config.environment.workers
    interval_seconds = _resolve_watchlist_interval(worker_env.watchlist_interval_s)
    timer_settings = settings.watchlist_timer
    timer_interval_seconds = timer_settings.interval_s
    timer_enabled = (
        worker_env.watchlist_timer_enabled
        if worker_env.watchlist_timer_enabled is not None
        else timer_settings.enabled
    )
    visibility_timeout = _resolve_visibility_timeout(worker_env.visibility_timeout_s)

    meta = {
        "watchlist": {
            "interval_s": interval_seconds,
            "concurrency": watchlist_config.max_concurrency,
            "max_per_tick": watchlist_config.max_per_tick,
            "retry_budget_per_artist": watchlist_config.retry_budget_per_artist,
            "backoff_base_ms": watchlist_config.backoff_base_ms,
            "jitter_pct": watchlist_config.jitter_pct,
            "timer_interval_s": timer_interval_seconds,
            "timer_enabled": timer_enabled,
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
            "workers_disabled_flag": worker_env.disable_workers,
            "workers_enabled_flag": worker_env.enabled_raw,
            "workers_enabled_override": worker_env.enabled_override,
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
        "metadata_update": False,
        "import": False,
        "orchestrator_scheduler": False,
        "orchestrator_dispatcher": False,
        "orchestrator_watchlist_timer": False,
    }

    state.import_worker = None
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

    state.metadata_update_worker = MetadataUpdateWorker(
        metadata_worker=state.rich_metadata_worker,
        matching_worker=getattr(app.state, "matching_worker", None),
    )
    worker_status["metadata_update"] = True

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
    state.import_worker = orchestrator.import_worker
    if state.import_worker is not None:
        await state.import_worker.start()
        worker_status["import"] = True
    worker_status["orchestrator_scheduler"] = True
    worker_status["orchestrator_dispatcher"] = True
    orchestrator_status["scheduler_running"] = True
    orchestrator_status["dispatcher_running"] = True
    orchestrator_status["scheduler_expected"] = True
    orchestrator_status["dispatcher_expected"] = True
    for job_type, enabled in orchestrator.enabled_jobs.items():
        orchestrator_status["enabled_jobs"][job_type] = bool(enabled)

    timer_settings = settings.watchlist_timer
    watchlist_timer = WatchlistTimer(
        config=config.watchlist,
        timer_config=timer_settings,
    )
    timer_enabled = watchlist_timer.enabled
    state.watchlist_timer = watchlist_timer
    orchestrator_status["watchlist_timer_expected"] = bool(timer_enabled)
    timer_started = await watchlist_timer.start()
    orchestrator_status["watchlist_timer_running"] = bool(timer_started)
    worker_status["orchestrator_watchlist_timer"] = bool(timer_started)
    if timer_started and watchlist_timer.task is not None:
        state.orchestrator_tasks.append(watchlist_timer.task)

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
    timer: WatchlistTimer | None = getattr(state, "watchlist_timer", None)

    if runtime is not None:
        runtime.dispatcher.request_stop()
        runtime.scheduler.request_stop()

    if stop_event is not None:
        stop_event.set()

    if timer is not None:
        await timer.stop()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    for attribute in (
        "orchestrator_tasks",
        "orchestrator_stop_event",
        "orchestrator_runtime",
        "watchlist_timer",
    ):
        if hasattr(state, attribute):
            delattr(state, attribute)

    await _stop_worker(getattr(state, "import_worker", None))
    if hasattr(state, "import_worker"):
        delattr(state, "import_worker")

    for attribute in (
        "artwork_worker",
        "lyrics_worker",
        "rich_metadata_worker",
        "metadata_update_worker",
    ):
        await _stop_worker(getattr(state, attribute, None))
        if hasattr(state, attribute):
            delattr(state, attribute)

    if orchestrator_status is not None:
        orchestrator_status["scheduler_running"] = False
        orchestrator_status["dispatcher_running"] = False
        orchestrator_status["scheduler_expected"] = False
        orchestrator_status["dispatcher_expected"] = False
        orchestrator_status["watchlist_timer_running"] = False
        orchestrator_status["watchlist_timer_expected"] = False
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

    response_cache = getattr(app.state, "response_cache", None)
    if response_cache is not None:
        await response_cache.clear()

    workers_enabled = _should_start_workers(config=config)
    _emit_worker_config_event(config, workers_enabled=workers_enabled)

    feature_flags = config.features
    app.state.feature_flags = feature_flags
    app.state.api_base_path = config.api_base_path
    orchestrator_status = _ensure_orchestrator_status(app)

    enable_artwork = feature_flags.enable_artwork
    enable_lyrics = feature_flags.enable_lyrics

    enabled_jobs = orchestrator_status.setdefault("enabled_jobs", {})
    enabled_jobs.update(
        {
            "sync": True,
            "matching": True,
            "retry": True,
            "watchlist": True,
            "artist_refresh": True,
            "artist_delta": True,
            "artwork": enable_artwork,
            "lyrics": enable_lyrics,
        }
    )
    orchestrator_status["scheduler_running"] = False
    orchestrator_status["dispatcher_running"] = False
    orchestrator_status["scheduler_expected"] = workers_enabled
    orchestrator_status["dispatcher_expected"] = workers_enabled
    worker_env = config.environment.workers
    timer_override = worker_env.watchlist_timer_enabled
    timer_env_enabled = (
        timer_override if timer_override is not None else settings.watchlist_timer.enabled
    )
    orchestrator_status["watchlist_timer_running"] = False
    orchestrator_status["watchlist_timer_expected"] = workers_enabled and timer_env_enabled

    worker_status: dict[str, bool] = {}

    if workers_enabled:
        worker_status = await _start_orchestrator_workers(
            app,
            config,
            enable_artwork=enable_artwork,
            enable_lyrics=enable_lyrics,
        )
    else:
        disable_reason = "runtime config"
        if worker_env.disable_workers:
            disable_reason = "HARMONY_DISABLE_WORKERS"
        elif worker_env.enabled_override is not None:
            disable_reason = "WORKERS_ENABLED override"
        logger.info("Background workers disabled (%s)", disable_reason)
        worker_status = {
            "artwork": False,
            "lyrics": False,
            "metadata": False,
            "metadata_update": False,
            "import": False,
            "orchestrator_scheduler": False,
            "orchestrator_dispatcher": False,
            "orchestrator_watchlist_timer": False,
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
    }

    flag_status = {
        "artwork": enable_artwork,
        "lyrics": enable_lyrics,
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


_docs_url = router_registry.compose_prefix(_API_BASE_PATH, "/docs")
_redoc_url = router_registry.compose_prefix(_API_BASE_PATH, "/redoc")
_openapi_url = router_registry.compose_prefix(_API_BASE_PATH, "/openapi.json")

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

install_middleware(app, _config_snapshot)


async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


_versioned_router = APIRouter()
_versioned_router.add_api_route("/", root, methods=["GET"], tags=["System"])
router_registry.register_all(
    app,
    base_path=_API_BASE_PATH,
    emit_log=True,
    router=_versioned_router,
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

    health_path = router_registry.compose_prefix(config.api_base_path, "/health")
    ready_path = router_registry.compose_prefix(config.api_base_path, "/ready")
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
