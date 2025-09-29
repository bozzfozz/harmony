"""Entry point for the Harmony FastAPI application."""

from __future__ import annotations

import inspect
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import sys
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Mapping

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

if sys.version_info < (3, 11):  # pragma: no cover - Python <3.11 fallback

    class ExceptionGroup(Exception):  # type: ignore[override]
        """Compatibility stub for Python versions without ExceptionGroup."""


from app.config import AppConfig
from app.core.config import DEFAULT_SETTINGS
from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_soulseek_client,
    get_spotify_client,
    require_api_key,
)
from app.db import get_session, init_db
from app.logging import configure_logging, get_logger
from app.errors import (
    AppError,
    ErrorCode,
    InternalServerError,
    rate_limit_meta,
    to_response,
)
from app.routers import (
    activity_router,
    backfill_router,
    download_router,
    dlq_router,
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
from app.services.health import HealthService
from app.services.secret_validation import SecretValidationService
from app.middleware.cache_conditional import CachePolicy, ConditionalCacheMiddleware
from app.services.cache import ResponseCache
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


def _format_metrics_float(value: float) -> str:
    if value == 0:
        return "0"
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return formatted or "0"


class _MetricsHistogram:
    def __init__(self, buckets: tuple[float, ...]) -> None:
        self._buckets = buckets
        self.counts = [0] * len(buckets)
        self.count = 0
        self.sum = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        self.sum += value
        for index, boundary in enumerate(self._buckets):
            if value <= boundary:
                self.counts[index] += 1


class MetricsRegistry:
    """Minimal Prometheus-style metrics registry."""

    def __init__(self, buckets: tuple[float, ...]) -> None:
        self._buckets = buckets
        self._lock = Lock()
        self._counters: dict[tuple[str, str, str], int] = {}
        self._histograms: dict[tuple[str, str, str], _MetricsHistogram] = {}
        self._custom_gauges: dict[str, dict[tuple[tuple[str, str], ...], float]] = {}
        self._custom_counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = {}
        self._custom_help: dict[str, tuple[str, str]] = {}

    def observe(self, method: str, path: str, status: str, duration: float) -> None:
        key = (method.upper(), path, status)
        value = duration if duration >= 0 else 0.0
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            histogram = self._histograms.get(key)
            if histogram is None:
                histogram = _MetricsHistogram(self._buckets)
                self._histograms[key] = histogram
            histogram.observe(value)

    def render(self, *, version: str) -> str:
        lines: list[str] = [
            "# HELP app_build_info Build information for the Harmony backend",
            "# TYPE app_build_info gauge",
            f'app_build_info{{version="{version}"}} 1',
        ]

        if self._counters:
            lines.append("# HELP app_requests_total Total number of processed HTTP requests")
            lines.append("# TYPE app_requests_total counter")
            for method, path, status in sorted(self._counters):
                value = self._counters[(method, path, status)]
                labels = self._format_labels(method, path, status)
                lines.append(f"app_requests_total{{{labels}}} {value}")

        lines.append("# HELP app_request_duration_seconds Request duration in seconds")
        lines.append("# TYPE app_request_duration_seconds histogram")
        for method, path, status in sorted(self._histograms):
            histogram = self._histograms[(method, path, status)]
            labels = self._format_labels(method, path, status)
            for bucket, count in zip(self._buckets, histogram.counts):
                bucket_value = _format_metrics_float(bucket)
                lines.append(
                    f'app_request_duration_seconds_bucket{{{labels},le="{bucket_value}"}} {count}'
                )
            lines.append(
                f'app_request_duration_seconds_bucket{{{labels},le="+Inf"}} {histogram.count}'
            )
            lines.append(f"app_request_duration_seconds_count{{{labels}}} {histogram.count}")
            lines.append(
                f"app_request_duration_seconds_sum{{{labels}}} {_format_metrics_float(histogram.sum)}"
            )

        custom_names = set(self._custom_gauges) | set(self._custom_counters)
        for name in sorted(custom_names):
            metric_type, help_text = self._custom_help.get(name, ("", ""))
            if help_text:
                lines.append(f"# HELP {name} {help_text}")
            if metric_type:
                lines.append(f"# TYPE {name} {metric_type}")
            if name in self._custom_gauges:
                series = self._custom_gauges[name]
                for labels, value in sorted(series.items()):
                    rendered_labels = self._format_custom_labels(labels)
                    formatted_value = _format_metrics_float(float(value))
                    lines.append(f"{name}{rendered_labels} {formatted_value}")
            if name in self._custom_counters:
                series = self._custom_counters[name]
                for labels, value in sorted(series.items()):
                    rendered_labels = self._format_custom_labels(labels)
                    formatted_value = _format_metrics_float(float(value))
                    lines.append(f"{name}{rendered_labels} {formatted_value}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _format_labels(method: str, path: str, status: str) -> str:
        escaped_path = path.replace("\\", "\\\\").replace('"', '\\"')
        return f'method="{method}",path="{escaped_path}",status="{status}"'

    @staticmethod
    def _normalise_label_items(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
        if not labels:
            return ()
        items = [(str(key), str(value)) for key, value in labels.items()]
        return tuple(sorted(items))

    @staticmethod
    def _format_custom_labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        escaped = []
        for key, value in labels:
            safe_key = key.replace("\\", "\\\\").replace('"', '\\"')
            safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
            escaped.append(f'{safe_key}="{safe_value}"')
        return "{" + ",".join(escaped) + "}"

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
        help_text: str | None = None,
    ) -> None:
        label_key = self._normalise_label_items(labels)
        with self._lock:
            series = self._custom_gauges.setdefault(name, {})
            series[label_key] = value
            if help_text:
                self._custom_help[name] = ("gauge", help_text)

    def increment_counter(
        self,
        name: str,
        *,
        amount: float = 1.0,
        labels: Mapping[str, str] | None = None,
        help_text: str | None = None,
    ) -> float:
        label_key = self._normalise_label_items(labels)
        with self._lock:
            series = self._custom_counters.setdefault(name, {})
            current = series.get(label_key, 0.0)
            new_value = current + amount
            series[label_key] = new_value
            if help_text:
                self._custom_help[name] = ("counter", help_text)
            return new_value

    def clear_metric(self, name: str) -> None:
        with self._lock:
            self._custom_gauges.pop(name, None)
            self._custom_counters.pop(name, None)
            self._custom_help.pop(name, None)


_METRIC_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _resolve_route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        return path
    return request.url.path


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
    router.include_router(dlq_router, prefix="/dlq", tags=["DLQ"])
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
        config=config.watchlist,
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

app.state.start_time = _APP_START_TIME
app.state.health_service = HealthService(
    start_time=_APP_START_TIME,
    version=app.version,
    config=_config_snapshot.health,
    session_factory=get_session,
)
app.state.secret_validation_service = SecretValidationService()
app.state.metrics_config = _config_snapshot.metrics
app.state.metrics_registry = MetricsRegistry(_METRIC_BUCKETS)

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
    vary_headers=("Authorization", "X-API-Key", "Origin", "Accept-Encoding"),
)


@app.middleware("http")
async def collect_metrics(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    metrics_config = getattr(request.app.state, "metrics_config", None)
    registry = getattr(request.app.state, "metrics_registry", None)
    if not metrics_config or not registry or not metrics_config.enabled:
        return await call_next(request)

    if request.url.path == metrics_config.path:
        return await call_next(request)

    route_path = _resolve_route_path(request)
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except HTTPException as exc:
        duration = time.perf_counter() - start_time
        registry.observe(request.method, route_path, str(exc.status_code), duration)
        raise
    except Exception:
        duration = time.perf_counter() - start_time
        registry.observe(request.method, route_path, "500", duration)
        raise

    duration = time.perf_counter() - start_time
    registry.observe(request.method, route_path, str(response.status_code), duration)
    return response


async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


_versioned_router = APIRouter()
_register_api_routes(_versioned_router, root)
app.include_router(_versioned_router, prefix=_format_router_prefix(_API_BASE_PATH))

if _LEGACY_ROUTES_ENABLED:
    legacy_router = APIRouter(route_class=LegacyLoggingRoute)
    _register_api_routes(legacy_router, root)
    app.include_router(legacy_router)


@app.get(
    _config_snapshot.metrics.path,
    include_in_schema=_config_snapshot.metrics.enabled,
)
async def metrics_endpoint(request: Request) -> PlainTextResponse:
    metrics_config = getattr(request.app.state, "metrics_config", _config_snapshot.metrics)
    logger.info(
        "Metrics endpoint requested",  # pragma: no cover - logging string
        extra={"event": "metrics.expose", "enabled": metrics_config.enabled},
    )
    if not metrics_config.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metrics disabled")

    registry = getattr(request.app.state, "metrics_registry", None)
    body = ""
    if registry is not None:
        body = registry.render(version=request.app.version)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


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

    metrics_config = config.metrics
    metrics_path = metrics_config.path
    if not metrics_config.enabled:
        paths.pop(metrics_path, None)
    else:
        metrics_item = paths.get(metrics_path)
        if isinstance(metrics_item, dict):
            metrics_operation = metrics_item.get("get")
            if isinstance(metrics_operation, dict):
                metrics_operation.setdefault("summary", "Prometheus metrics")
                metrics_operation.setdefault(
                    "description",
                    "Exposes Prometheus compatible metrics in text format.",
                )
                responses = metrics_operation.setdefault("responses", {})
                responses["200"] = {
                    "description": "Prometheus metrics payload",
                    "content": {"text/plain; version=0.0.4": {"schema": {"type": "string"}}},
                }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
