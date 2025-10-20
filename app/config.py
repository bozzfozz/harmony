"""Application configuration utilities for Harmony."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.logging import get_logger
from app.logging_events import log_event
from app.utils.priority import parse_priority_map

logger = get_logger(__name__)

DEFAULT_APP_PORT = 8080
_LEGACY_APP_PORT_ENV_VARS: tuple[str, ...] = (
    "PORT",
    "UVICORN_PORT",
    "SERVICE_PORT",
    "WEB_PORT",
    "FRONTEND_PORT",
)


_RUNTIME_ENV_CACHE: dict[str, str] | None = None


@dataclass(slots=True, frozen=True)
class ConfigTemplateEntry:
    name: str
    default: Any
    comment: str


@dataclass(slots=True, frozen=True)
class ConfigTemplateSection:
    name: str
    comment: str
    entries: tuple[ConfigTemplateEntry, ...]


DEFAULT_CONFIG_FILE_PATH = Path("/data/harmony.yml")


def _load_env_file(path: Path) -> dict[str, str]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    env_values: dict[str, str] = {}
    for line in contents.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if not sep:
            continue
        env_values[key.strip()] = value.strip().strip('"').strip("'")
    return env_values


def _resolve_config_file_path(env: Mapping[str, Any]) -> Path | None:
    raw_path = env.get("HARMONY_CONFIG_FILE")
    if raw_path:
        return Path(str(raw_path)).expanduser()
    if env.get("PYTEST_CURRENT_TEST"):
        return None
    return DEFAULT_CONFIG_FILE_PATH


def _render_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple | set):
        rendered_items = [_render_yaml_scalar(item) for item in value]
        return f"[{', '.join(rendered_items)}]"
    text = str(value)
    if _needs_yaml_quotes(text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _needs_yaml_quotes(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    if lowered in {"true", "false", "null", "~"}:
        return True
    if text[0] in {"-", "#", "[", "{", "!"}:
        return True
    if text[0].isdigit() and not text.isdigit():
        return True
    for char in text:
        if char.isspace() or char in {":", "#", ",", "[", "]", "{", "}", '"', "'"}:
            return True
    return False


def _render_config_template() -> str:
    lines = [
        "# Harmony runtime configuration",
        "#",
        "# This file is generated automatically on first start. Update the values",
        "# as needed and restart the container to apply changes. Environment",
        "# variables still take precedence over values defined here.",
        "",
    ]
    for section in _CONFIG_TEMPLATE_SECTIONS:
        lines.append(f"# {section.comment}")
        lines.append(f"{section.name}:")
        for entry in section.entries:
            if entry.comment:
                lines.append(f"  # {entry.comment}")
            rendered = _render_yaml_scalar(entry.default)
            lines.append(f"  {entry.name}: {rendered}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _ensure_config_file(path: Path) -> None:
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_config_template(), encoding="utf-8")
        logger.info("Created default configuration file", extra={"path": str(path)})
    except OSError as exc:
        logger.warning(
            "Unable to create configuration file", extra={"path": str(path), "error": str(exc)}
        )


def _flatten_yaml_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    flattened: dict[str, Any] = {}
    stack: list[tuple[str | None, Any]] = [(None, data)]
    while stack:
        prefix, node = stack.pop()
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_str = str(key)
                stack.append((key_str, value))
        else:
            if prefix is not None:
                flattened[prefix] = node
    return flattened


def _parse_yaml_scalar(text: str) -> Any:
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"null", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        items: list[Any] = []
        current = []
        quote: str | None = None
        escape = False
        for char in inner:
            if escape:
                current.append(char)
                escape = False
                continue
            if char == "\\" and quote == '"':
                escape = True
                current.append(char)
                continue
            if char in {'"', "'"}:
                if quote is None:
                    quote = char
                elif quote == char:
                    quote = None
                current.append(char)
                continue
            if char == "," and quote is None:
                item_text = "".join(current).strip()
                if item_text:
                    items.append(_parse_yaml_scalar(item_text))
                current = []
                continue
            current.append(char)
        if current:
            item_text = "".join(current).strip()
            if item_text:
                items.append(_parse_yaml_scalar(item_text))
        return items
    if text.startswith('"') and text.endswith('"'):
        inner = text[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    try:
        if "." in text or "e" in lowered or "E" in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _parse_yaml_like(contents: str) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    current_section: dict[str, Any] | None = None
    for raw_line in contents.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith(" "):
            if stripped.endswith(":"):
                section_name = stripped[:-1].strip()
                if section_name:
                    current_section = {}
                    parsed[section_name] = current_section
                else:
                    current_section = None
            else:
                current_section = None
            continue
        if current_section is None:
            continue
        if ":" not in stripped:
            continue
        key_part, value_part = stripped.split(":", 1)
        key = key_part.strip()
        value = _parse_yaml_scalar(value_part.strip())
        current_section[key] = value
    return parsed


def _stringify_env_values(values: Mapping[str, Any]) -> dict[str, str]:
    env_values: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, list | tuple | set):
            env_values[key] = ",".join(str(item) for item in value)
            continue
        if isinstance(value, bool):
            env_values[key] = "true" if value else "false"
            continue
        env_values[key] = str(value)
    return env_values


def _load_yaml_config(path: Path) -> dict[str, str]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    parsed = _parse_yaml_like(contents)
    flattened = _flatten_yaml_mapping(parsed)
    if not flattened:
        return {}
    return _stringify_env_values(flattened)


def load_runtime_env(
    *,
    env_file: str | os.PathLike[str] | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Load runtime environment values applying .env before explicit environment."""

    env: dict[str, str] = {}
    source = dict(base_env or os.environ)

    config_path = _resolve_config_file_path(source)
    if config_path is not None:
        _ensure_config_file(config_path)
        env.update(_load_yaml_config(config_path))

    path = Path(env_file) if env_file is not None else Path(".env")
    if path.exists() and path.is_file():
        env.update(_load_env_file(path))

    env.update({key: str(value) for key, value in source.items() if value is not None})
    return env


def get_runtime_env() -> Mapping[str, str]:
    """Return the cached runtime environment mapping."""

    global _RUNTIME_ENV_CACHE
    if _RUNTIME_ENV_CACHE is None:
        _RUNTIME_ENV_CACHE = load_runtime_env()
    return _RUNTIME_ENV_CACHE


def override_runtime_env(runtime_env: Mapping[str, str] | None) -> None:
    """Override the cached runtime environment (primarily for testing)."""

    global _RUNTIME_ENV_CACHE
    if runtime_env is None:
        _RUNTIME_ENV_CACHE = None
    else:
        _RUNTIME_ENV_CACHE = dict(runtime_env)


def get_env(name: str, default: str | None = None) -> str | None:
    """Return an environment variable honoring ENV > .env > defaults."""

    env = get_runtime_env()
    return env.get(name, default)


def _env_value(env: Mapping[str, Any], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    return str(value)


def _legacy_port_aliases(env: Mapping[str, Any]) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []
    for candidate in _LEGACY_APP_PORT_ENV_VARS:
        value = _env_value(env, candidate)
        if value is None:
            continue
        stripped = value.strip()
        if not stripped:
            continue
        aliases.append((candidate, stripped))
    return aliases


def resolve_app_port(env: Mapping[str, Any] | None = None) -> int:
    """Return the configured application port constrained to valid TCP ranges."""

    runtime_env: Mapping[str, Any] = env or get_runtime_env()
    aliases = _legacy_port_aliases(runtime_env)
    raw_value = _env_value(runtime_env, "APP_PORT")
    source_name = "APP_PORT"

    if raw_value is not None:
        stripped = raw_value.strip()
        if not stripped:
            raw_value = None
        else:
            raw_value = stripped

    if raw_value is None and aliases:
        alias_name, alias_value = aliases[0]
        source_name = alias_name
        raw_value = alias_value
        logger.warning(
            "Legacy port alias %s=%r detected without APP_PORT; using alias value. "
            "Configure APP_PORT to silence this warning.",
            alias_name,
            alias_value,
        )
    elif raw_value is not None and aliases:
        alias_rendered = ", ".join(f"{name}={value!r}" for name, value in aliases)
        logger.info(
            "Ignoring legacy port aliases %s because APP_PORT=%r is set.",
            alias_rendered,
            raw_value,
        )
    port = _bounded_int(
        raw_value,
        default=DEFAULT_APP_PORT,
        minimum=1,
        maximum=65535,
    )

    if raw_value is None:
        return port

    try:
        numeric = int(str(raw_value))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid APP_PORT value %r from %s; falling back to default %s.",
            raw_value,
            source_name,
            DEFAULT_APP_PORT,
        )
        return port

    if not (1 <= numeric <= 65535):
        logger.warning(
            "APP_PORT value %r from %s outside allowed range; clamped to %s.",
            raw_value,
            source_name,
            port,
        )

    return port


@dataclass(slots=True)
class SpotifyConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    scope: str
    free_import_max_lines: int
    free_import_max_file_bytes: int
    free_import_max_playlist_links: int
    free_import_hard_cap_multiplier: int
    free_accept_user_urls: bool
    backfill_max_items: int
    backfill_cache_ttl_seconds: int


@dataclass(slots=True)
class OAuthConfig:
    callback_port: int
    redirect_uri: str
    manual_callback_enabled: bool
    session_ttl_minutes: int
    public_host_hint: str | None
    public_base: str
    split_mode: bool
    state_dir: str
    state_ttl_seconds: int
    store_hash_code_verifier: bool


@dataclass(slots=True)
class SoulseekConfig:
    base_url: str
    api_key: str | None
    timeout_ms: int
    retry_max: int
    retry_backoff_base_ms: int
    retry_jitter_pct: float
    preferred_formats: tuple[str, ...]
    max_results: int


_SUPPORTED_IDEMPOTENCY_BACKENDS = {"memory", "sqlite"}
DEFAULT_IDEMPOTENCY_BACKEND = "sqlite"


@dataclass(slots=True)
class HdmConfig:
    downloads_dir: str
    music_dir: str
    worker_concurrency: int
    batch_max_items: int
    size_stable_seconds: int
    max_retries: int
    slskd_timeout_seconds: int
    move_template: str
    idempotency_backend: str = DEFAULT_IDEMPOTENCY_BACKEND
    idempotency_sqlite_path: str = ""

    def __post_init__(self) -> None:
        if not self.idempotency_backend:
            self.idempotency_backend = DEFAULT_IDEMPOTENCY_BACKEND
        if not self.idempotency_sqlite_path:
            base = Path(self.downloads_dir).expanduser()
            self.idempotency_sqlite_path = str(base / ".harmony" / "idempotency.db")

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> HdmConfig:
        downloads_dir = str(env.get("DOWNLOADS_DIR") or DEFAULT_DOWNLOADS_DIR)
        music_dir = str(env.get("MUSIC_DIR") or DEFAULT_MUSIC_DIR)
        backend = _parse_idempotency_backend(env.get("IDEMPOTENCY_BACKEND"))
        sqlite_path = _resolve_idempotency_sqlite_path(env, downloads_dir)
        return cls(
            downloads_dir=downloads_dir,
            music_dir=music_dir,
            worker_concurrency=_bounded_int(
                env.get("WORKER_CONCURRENCY"),
                default=DEFAULT_DOWNLOAD_WORKER_CONCURRENCY,
                minimum=1,
            ),
            batch_max_items=_bounded_int(
                env.get("BATCH_MAX_ITEMS"),
                default=DEFAULT_DOWNLOAD_BATCH_MAX_ITEMS,
                minimum=1,
            ),
            size_stable_seconds=_bounded_int(
                env.get("SIZE_STABLE_SEC"),
                default=DEFAULT_SIZE_STABLE_SECONDS,
                minimum=1,
            ),
            max_retries=_bounded_int(
                env.get("MAX_RETRIES"),
                default=DEFAULT_DOWNLOAD_MAX_RETRIES,
                minimum=1,
            ),
            slskd_timeout_seconds=_resolve_slskd_timeout_seconds(env),
            move_template=str(env.get("MOVE_TEMPLATE") or DEFAULT_MOVE_TEMPLATE),
            idempotency_backend=backend,
            idempotency_sqlite_path=sqlite_path,
        )


# Backward compatibility alias (remove in v1.2.0)
DownloadFlowConfig = HdmConfig


def _resolve_slskd_timeout_seconds(env: Mapping[str, Any]) -> int:
    seconds_value = env.get("SLSKD_TIMEOUT_SEC")
    if seconds_value is None:
        seconds_value = env.get("SLSDK_TIMEOUT_SEC")
    if seconds_value is not None:
        return _bounded_int(
            seconds_value,
            default=DEFAULT_SLSKD_TIMEOUT_SEC,
            minimum=1,
        )

    timeout_ms_value = env.get("SLSKD_TIMEOUT_MS")
    if timeout_ms_value is not None:
        timeout_ms = _coerce_int(timeout_ms_value, default=0)
        if timeout_ms > 0:
            seconds = max(1, (timeout_ms + 999) // 1000)
            return _bounded_int(
                seconds,
                default=DEFAULT_SLSKD_TIMEOUT_SEC,
                minimum=1,
            )

    return DEFAULT_SLSKD_TIMEOUT_SEC


def _parse_idempotency_backend(raw_value: Any) -> str:
    if raw_value is None:
        return DEFAULT_IDEMPOTENCY_BACKEND
    backend = str(raw_value).strip().lower()
    if not backend:
        return DEFAULT_IDEMPOTENCY_BACKEND
    if backend not in _SUPPORTED_IDEMPOTENCY_BACKENDS:
        options = ", ".join(sorted(_SUPPORTED_IDEMPOTENCY_BACKENDS))
        raise ValueError(f"IDEMPOTENCY_BACKEND must be one of: {options}")
    return backend


def _resolve_idempotency_sqlite_path(env: Mapping[str, Any], downloads_dir: str) -> str:
    raw_path = env.get("IDEMPOTENCY_SQLITE_PATH")
    if raw_path is None or not str(raw_path).strip():
        base = Path(downloads_dir).expanduser()
        return str(base / ".harmony" / "idempotency.db")
    return str(Path(str(raw_path)).expanduser())


@dataclass(slots=True)
class LoggingConfig:
    level: str


@dataclass(slots=True)
class DatabaseConfig:
    url: str


@dataclass(slots=True)
class ArtworkFallbackConfig:
    enabled: bool
    provider: str
    timeout_seconds: float
    max_bytes: int


@dataclass(slots=True)
class ArtworkPostProcessingConfig:
    enabled: bool = False
    hooks: tuple[str, ...] = ()


@dataclass(slots=True)
class ArtworkConfig:
    directory: str
    timeout_seconds: float
    max_bytes: int
    concurrency: int
    min_edge: int
    min_bytes: int
    fallback: ArtworkFallbackConfig
    post_processing: ArtworkPostProcessingConfig = field(
        default_factory=ArtworkPostProcessingConfig
    )


@dataclass(slots=True)
class FreeIngestConfig:
    max_playlists: int
    max_tracks: int
    batch_size: int


@dataclass(slots=True)
class IngestConfig:
    batch_size: int
    max_pending_jobs: int


@dataclass(slots=True)
class FeatureFlags:
    enable_artwork: bool
    enable_lyrics: bool
    enable_legacy_routes: bool
    enable_artist_cache_invalidation: bool
    enable_admin_api: bool


@dataclass(slots=True, frozen=True)
class UiConfig:
    live_updates: Literal["polling", "sse"]


_UI_LIVE_UPDATE_MODES: frozenset[str] = frozenset({"polling", "sse"})
_DEFAULT_UI_LIVE_UPDATES = "polling"


def _parse_ui_config(env: Mapping[str, Any]) -> UiConfig:
    raw_mode = _env_value(env, "UI_LIVE_UPDATES")
    if raw_mode is None or not raw_mode.strip():
        return UiConfig(live_updates=_DEFAULT_UI_LIVE_UPDATES)

    normalized = raw_mode.strip().lower()
    if normalized not in _UI_LIVE_UPDATE_MODES:
        logger.warning(
            "Unknown UI_LIVE_UPDATES value %s; defaulting to %s",
            raw_mode,
            _DEFAULT_UI_LIVE_UPDATES,
        )
        normalized = _DEFAULT_UI_LIVE_UPDATES
    return UiConfig(live_updates=normalized)  # type: ignore[arg-type]


@dataclass(slots=True)
class AdminConfig:
    api_enabled: bool
    staleness_max_minutes: int
    retry_budget_max: int


@dataclass(slots=True)
class ArtistSyncConfig:
    prune_removed: bool
    hard_delete: bool


@dataclass(slots=True)
class IntegrationsConfig:
    enabled: tuple[str, ...]
    timeouts_ms: dict[str, int]
    max_concurrency: int


@dataclass(slots=True)
class HealthConfig:
    db_timeout_ms: int
    dependency_timeout_ms: int
    dependencies: tuple[str, ...]
    require_database: bool


@dataclass(slots=True)
class WatchlistWorkerConfig:
    max_concurrency: int
    max_per_tick: int
    spotify_timeout_ms: int
    slskd_search_timeout_ms: int
    tick_budget_ms: int
    backoff_base_ms: int
    retry_max: int
    jitter_pct: float
    shutdown_grace_ms: int
    db_io_mode: str
    retry_budget_per_artist: int
    cooldown_minutes: int


@dataclass(slots=True, frozen=True)
class ExternalCallPolicy:
    timeout_ms: int
    retry_max: int
    backoff_base_ms: int
    jitter_pct: float

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> ExternalCallPolicy:
        timeout_ms = _bounded_int(
            env.get("EXTERNAL_TIMEOUT_MS"),
            default=DEFAULT_EXTERNAL_TIMEOUT_MS,
            minimum=100,
        )
        retry_max = _bounded_int(
            env.get("EXTERNAL_RETRY_MAX"),
            default=DEFAULT_EXTERNAL_RETRY_MAX,
            minimum=0,
        )
        backoff_base = _bounded_int(
            env.get("EXTERNAL_BACKOFF_BASE_MS"),
            default=DEFAULT_EXTERNAL_BACKOFF_BASE_MS,
            minimum=1,
        )
        jitter_pct = _parse_jitter_value(
            env.get("EXTERNAL_JITTER_PCT"),
            default_pct=DEFAULT_EXTERNAL_JITTER_PCT,
        )
        return cls(
            timeout_ms=timeout_ms,
            retry_max=retry_max,
            backoff_base_ms=backoff_base,
            jitter_pct=jitter_pct,
        )


@dataclass(slots=True, frozen=True)
class ProviderProfile:
    name: str
    policy: ExternalCallPolicy


@dataclass(slots=True, frozen=True)
class WatchlistTimerConfig:
    enabled: bool
    interval_s: float

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> WatchlistTimerConfig:
        enabled = _as_bool(
            (str(env.get("WATCHLIST_TIMER_ENABLED")) if "WATCHLIST_TIMER_ENABLED" in env else None),
            default=DEFAULT_WATCHLIST_TIMER_ENABLED,
        )
        interval = _bounded_float(
            env.get("WATCHLIST_TIMER_INTERVAL_S"),
            default=DEFAULT_WATCHLIST_TIMER_INTERVAL_S,
            minimum=0.0,
        )
        return cls(enabled=enabled, interval_s=interval)


@dataclass(slots=True, frozen=True)
class OrchestratorConfig:
    workers_enabled: bool
    global_concurrency: int
    pool_sync: int
    pool_matching: int
    pool_retry: int
    pool_artist_refresh: int
    pool_artist_delta: int
    priority_map: dict[str, int]
    visibility_timeout_s: int
    heartbeat_s: int
    poll_interval_ms: int
    poll_interval_max_ms: int

    def pool_limits(self) -> dict[str, int]:
        return {
            "sync": max(1, self.pool_sync or self.global_concurrency),
            "matching": max(1, self.pool_matching or self.global_concurrency),
            "retry": max(1, self.pool_retry or self.global_concurrency),
            "artist_refresh": max(1, self.pool_artist_refresh or self.global_concurrency),
            "artist_delta": max(1, self.pool_artist_delta or self.global_concurrency),
        }

    @classmethod
    def from_env(cls, env: Mapping[str, Any]) -> OrchestratorConfig:
        workers_enabled = _as_bool(
            str(env.get("WORKERS_ENABLED")) if "WORKERS_ENABLED" in env else None,
            default=DEFAULT_ORCHESTRATOR_WORKERS_ENABLED,
        )
        global_limit = _bounded_int(
            env.get("ORCH_GLOBAL_CONCURRENCY"),
            default=DEFAULT_ORCH_GLOBAL_CONCURRENCY,
            minimum=1,
        )
        pool_sync = _bounded_int(
            env.get("ORCH_POOL_SYNC"),
            default=DEFAULT_ORCH_POOL_SYNC,
            minimum=1,
        )
        pool_matching = _bounded_int(
            env.get("ORCH_POOL_MATCHING"),
            default=DEFAULT_ORCH_POOL_MATCHING,
            minimum=1,
        )
        pool_retry = _bounded_int(
            env.get("ORCH_POOL_RETRY"),
            default=DEFAULT_ORCH_POOL_RETRY,
            minimum=1,
        )
        pool_artist_refresh = _bounded_int(
            env.get("ORCH_POOL_ARTIST_REFRESH"),
            default=DEFAULT_ORCH_POOL_ARTIST_REFRESH,
            minimum=1,
        )
        pool_artist_delta = _bounded_int(
            env.get("ORCH_POOL_ARTIST_DELTA"),
            default=DEFAULT_ORCH_POOL_ARTIST_DELTA,
            minimum=1,
        )
        artist_pool_raw = env.get("ARTIST_POOL_CONCURRENCY")
        if artist_pool_raw is not None:
            shared_pool = _bounded_int(
                artist_pool_raw,
                default=DEFAULT_ARTIST_POOL_CONCURRENCY,
                minimum=1,
            )
            pool_artist_refresh = shared_pool
            pool_artist_delta = shared_pool
        visibility_timeout = _bounded_int(
            env.get("ORCH_VISIBILITY_TIMEOUT_S"),
            default=DEFAULT_ORCH_VISIBILITY_TIMEOUT_S,
            minimum=5,
        )
        heartbeat_s = _bounded_int(
            env.get("ORCH_HEARTBEAT_S"),
            default=DEFAULT_ORCH_HEARTBEAT_S,
            minimum=1,
        )
        poll_interval = _bounded_int(
            env.get("ORCH_POLL_INTERVAL_MS"),
            default=DEFAULT_ORCH_POLL_INTERVAL_MS,
            minimum=10,
        )
        poll_interval_max = _bounded_int(
            env.get("ORCH_POLL_INTERVAL_MAX_MS"),
            default=DEFAULT_ORCH_POLL_INTERVAL_MAX_MS,
            minimum=poll_interval,
        )
        priority_map = _parse_priority_map(env)
        artist_priority_raw = env.get("ARTIST_PRIORITY")
        if artist_priority_raw is not None:
            artist_priority = _bounded_int(
                artist_priority_raw,
                default=DEFAULT_ARTIST_PRIORITY,
                minimum=0,
            )
            priority_map["artist_refresh"] = artist_priority
            priority_map["artist_scan"] = artist_priority
            priority_map["artist_delta"] = artist_priority
        if "artist_scan" not in priority_map and "artist_delta" in priority_map:
            priority_map["artist_scan"] = priority_map["artist_delta"]
        if "artist_delta" not in priority_map and "artist_scan" in priority_map:
            priority_map["artist_delta"] = priority_map["artist_scan"]
        return cls(
            workers_enabled=workers_enabled,
            global_concurrency=global_limit,
            pool_sync=pool_sync,
            pool_matching=pool_matching,
            pool_retry=pool_retry,
            pool_artist_refresh=pool_artist_refresh,
            pool_artist_delta=pool_artist_delta,
            priority_map=priority_map,
            visibility_timeout_s=visibility_timeout,
            heartbeat_s=heartbeat_s,
            poll_interval_ms=poll_interval,
            poll_interval_max_ms=poll_interval_max,
        )


@dataclass(slots=True, frozen=True)
class RetryPolicyConfig:
    max_attempts: int
    base_seconds: float
    jitter_pct: float


@dataclass(slots=True)
class MatchingConfig:
    edition_aware: bool
    fuzzy_max_candidates: int
    min_artist_similarity: float
    complete_threshold: float
    nearly_threshold: float


@dataclass(slots=True, frozen=True)
class WorkerEnvironmentConfig:
    disable_workers: bool
    enabled_override: bool | None
    enabled_raw: str | None
    visibility_timeout_s: int | None
    watchlist_interval_s: float | None
    watchlist_timer_enabled: bool | None


@dataclass(slots=True, frozen=True)
class EnvironmentConfig:
    profile: str
    is_dev: bool
    is_test: bool
    is_staging: bool
    is_prod: bool
    workers: WorkerEnvironmentConfig


@dataclass(slots=True)
class AppConfig:
    spotify: SpotifyConfig
    oauth: OAuthConfig
    soulseek: SoulseekConfig
    logging: LoggingConfig
    database: DatabaseConfig
    artwork: ArtworkConfig
    ingest: IngestConfig
    free_ingest: FreeIngestConfig
    features: FeatureFlags
    ui: UiConfig
    artist_sync: ArtistSyncConfig
    integrations: IntegrationsConfig
    security: SecurityConfig
    middleware: MiddlewareConfig
    api_base_path: str
    health: HealthConfig
    watchlist: WatchlistWorkerConfig
    matching: MatchingConfig
    environment: EnvironmentConfig
    admin: AdminConfig


@dataclass(slots=True, frozen=True)
class SecurityProfileDefaults:
    name: str
    require_auth: bool
    rate_limiting: bool


DEFAULT_SECURITY_PROFILE = "default"
_SECURITY_PROFILE_DEFAULTS: Mapping[str, SecurityProfileDefaults] = {
    "default": SecurityProfileDefaults(
        name="default",
        require_auth=False,
        rate_limiting=False,
    ),
    "dev": SecurityProfileDefaults(
        name="dev",
        require_auth=False,
        rate_limiting=False,
    ),
    "test": SecurityProfileDefaults(
        name="test",
        require_auth=False,
        rate_limiting=False,
    ),
    "staging": SecurityProfileDefaults(
        name="staging",
        require_auth=False,
        rate_limiting=False,
    ),
    "prod": SecurityProfileDefaults(
        name="prod",
        require_auth=True,
        rate_limiting=True,
    ),
}

_SECURITY_PROFILE_ALIASES: Mapping[str, str] = {
    "production": "prod",
    "live": "prod",
    "development": "dev",
    "local": "dev",
    "testing": "test",
}


@dataclass(slots=True)
class SecurityConfig:
    profile: str
    api_keys: tuple[str, ...]
    allowlist: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    _require_auth_default: bool
    _rate_limiting_default: bool
    _require_auth_override: bool | None = None
    _rate_limiting_override: bool | None = None

    @property
    def require_auth_default(self) -> bool:
        return self._require_auth_default

    @property
    def rate_limiting_default(self) -> bool:
        return self._rate_limiting_default

    def resolve_require_auth(self) -> bool:
        if self._require_auth_override is not None:
            return self._require_auth_override
        return self._require_auth_default

    def resolve_rate_limiting_enabled(self) -> bool:
        if self._rate_limiting_override is not None:
            return self._rate_limiting_override
        return self._rate_limiting_default

    @property
    def require_auth(self) -> bool:
        return self.resolve_require_auth()

    @require_auth.setter
    def require_auth(self, value: bool | None) -> None:
        self._require_auth_override = bool(value) if value is not None else None

    @property
    def rate_limiting_enabled(self) -> bool:
        return self.resolve_rate_limiting_enabled()

    @rate_limiting_enabled.setter
    def rate_limiting_enabled(self, value: bool | None) -> None:
        self._rate_limiting_override = bool(value) if value is not None else None

    def clear_profile_overrides(self) -> None:
        self._require_auth_override = None
        self._rate_limiting_override = None


def _resolve_security_profile(
    env: Mapping[str, Any],
) -> tuple[str, SecurityProfileDefaults]:
    raw = str(env.get("HARMONY_PROFILE") or "").strip().lower()
    if not raw:
        key = DEFAULT_SECURITY_PROFILE
    else:
        candidate = _SECURITY_PROFILE_ALIASES.get(raw, raw)
        if candidate not in _SECURITY_PROFILE_DEFAULTS:
            logger.warning(
                "Unknown HARMONY_PROFILE value %s; defaulting to %s",
                raw,
                DEFAULT_SECURITY_PROFILE,
            )
            key = DEFAULT_SECURITY_PROFILE
        else:
            key = candidate
    defaults = _SECURITY_PROFILE_DEFAULTS[key]
    return defaults.name, defaults


@dataclass(slots=True)
class RequestMiddlewareConfig:
    header_name: str


@dataclass(slots=True)
class RateLimitMiddlewareConfig:
    enabled: bool
    bucket_capacity: int
    refill_per_second: float


@dataclass(slots=True, frozen=True)
class CacheRule:
    pattern: str
    ttl: int | None
    stale_while_revalidate: int | None


@dataclass(slots=True)
class CacheMiddlewareConfig:
    enabled: bool
    default_ttl: int
    max_items: int
    etag_strategy: str
    fail_open: bool
    stale_while_revalidate: int | None
    cacheable_paths: tuple[CacheRule, ...]
    write_through: bool
    log_evictions: bool


@dataclass(slots=True)
class CorsMiddlewareConfig:
    allowed_origins: tuple[str, ...]
    allowed_headers: tuple[str, ...]
    allowed_methods: tuple[str, ...]


@dataclass(slots=True)
class GZipMiddlewareConfig:
    min_size: int


@dataclass(slots=True)
class MiddlewareConfig:
    request_id: RequestMiddlewareConfig
    rate_limit: RateLimitMiddlewareConfig
    cache: CacheMiddlewareConfig
    cors: CorsMiddlewareConfig
    gzip: GZipMiddlewareConfig


@dataclass(slots=True, frozen=True)
class Settings:
    orchestrator: OrchestratorConfig
    external: ExternalCallPolicy
    watchlist_timer: WatchlistTimerConfig
    hdm: HdmConfig
    provider_profiles: dict[str, ProviderProfile]
    retry_policy: RetryPolicyConfig

    @classmethod
    def load(cls, env: Mapping[str, Any] | None = None) -> Settings:
        env_map: dict[str, Any] = dict(env or get_runtime_env())
        orchestrator = OrchestratorConfig.from_env(env_map)
        external = ExternalCallPolicy.from_env(env_map)
        watchlist_timer = WatchlistTimerConfig.from_env(env_map)
        hdm = HdmConfig.from_env(env_map)
        logger.info(
            "Resolved HDM directories",
            extra={
                "event": "config.hdm.paths",
                "downloads_dir": hdm.downloads_dir,
                "music_dir": hdm.music_dir,
                "oauth_state_dir": str(env_map.get("OAUTH_STATE_DIR") or ""),
                "oauth_split_mode": env_map.get("OAUTH_SPLIT_MODE"),
            },
        )
        profiles = _load_provider_profiles(env_map, external)
        return cls(
            orchestrator=orchestrator,
            external=external,
            watchlist_timer=watchlist_timer,
            hdm=hdm,
            provider_profiles=profiles,
            retry_policy=_load_retry_policy(env_map),
        )


DEFAULT_DB_URL_DEV = "sqlite+aiosqlite:///./harmony.db"
DEFAULT_DB_URL_PROD = "sqlite+aiosqlite:///data/harmony.db"
DEFAULT_DB_URL_TEST = "sqlite+aiosqlite:///:memory:"
DEFAULT_SOULSEEK_URL = "http://localhost:5030"
DEFAULT_SOULSEEK_PORT = urlparse(DEFAULT_SOULSEEK_URL).port or 5030
DEFAULT_SPOTIFY_SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"
DEFAULT_ARTWORK_DIR = "./artwork"
DEFAULT_ARTWORK_TIMEOUT = 15.0
DEFAULT_ARTWORK_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_ARTWORK_CONCURRENCY = 2
DEFAULT_ARTWORK_MIN_EDGE = 1000
DEFAULT_ARTWORK_MIN_BYTES = 150_000
DEFAULT_ARTWORK_FALLBACK_TIMEOUT = 12.0
DEFAULT_ARTWORK_FALLBACK_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_FREE_IMPORT_MAX_LINES = 200
DEFAULT_FREE_IMPORT_MAX_FILE_BYTES = 1_048_576
DEFAULT_FREE_IMPORT_MAX_PLAYLIST_LINKS = 1_000
DEFAULT_FREE_IMPORT_HARD_CAP_MULTIPLIER = 10
DEFAULT_FREE_INGEST_MAX_PLAYLISTS = 100
DEFAULT_FREE_INGEST_MAX_TRACKS = 5_000
DEFAULT_FREE_INGEST_BATCH_SIZE = 500
DEFAULT_INGEST_BATCH_SIZE = 500
DEFAULT_INGEST_MAX_PENDING_JOBS = 100
DEFAULT_BACKFILL_MAX_ITEMS = 2_000
DEFAULT_BACKFILL_CACHE_TTL = 604_800
DEFAULT_API_BASE_PATH = "/api/v1"
DEFAULT_ALLOWLIST_SUFFIXES = (
    "/health",
    "/ready",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
)
# Exclude `/spotify/status` from caching so credential changes are reflected immediately.
DEFAULT_CACHEABLE_PATH_PATTERNS = (
    "^/$|30|120",
    "^/activity$|60|180",
    "^/activity/export$|300|600",
    "^/spotify(?:/(?!status$).*)?$|45|180",
)
DEFAULT_PROVIDER_MAX_CONCURRENCY = 4
DEFAULT_SLSKD_TIMEOUT_MS = 8_000
DEFAULT_SLSKD_RETRY_MAX = 3
DEFAULT_SLSKD_RETRY_BACKOFF_BASE_MS = 250
DEFAULT_SLSKD_RETRY_JITTER_PCT = 20.0
DEFAULT_SLSKD_PREFERRED_FORMATS = ("FLAC", "ALAC", "APE", "MP3")
DEFAULT_SLSKD_MAX_RESULTS = 50
DEFAULT_HEALTH_DB_TIMEOUT_MS = 500
DEFAULT_HEALTH_DEP_TIMEOUT_MS = 800
DEFAULT_WATCHLIST_MAX_CONCURRENCY = 3
DEFAULT_WATCHLIST_MAX_PER_TICK = 20
DEFAULT_WATCHLIST_SPOTIFY_TIMEOUT_MS = 8_000
DEFAULT_WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS = 12_000
DEFAULT_WATCHLIST_TICK_BUDGET_MS = 8_000
DEFAULT_WATCHLIST_BACKOFF_BASE_MS = 250
DEFAULT_WATCHLIST_RETRY_MAX = 3

DEFAULT_ORCHESTRATOR_WORKERS_ENABLED = True
DEFAULT_ORCH_GLOBAL_CONCURRENCY = 8
DEFAULT_ORCH_POOL_SYNC = 4
DEFAULT_ORCH_POOL_MATCHING = 4
DEFAULT_ORCH_POOL_RETRY = 2
DEFAULT_ORCH_POOL_ARTIST_REFRESH = 2
DEFAULT_ORCH_POOL_ARTIST_DELTA = 2
DEFAULT_ORCH_PRIORITY_MAP = {
    "sync": 100,
    "matching": 90,
    "retry": 80,
    "artist_refresh": 50,
    "artist_scan": 45,
    "artist_delta": 45,
}
DEFAULT_ARTIST_PRIORITY = DEFAULT_ORCH_PRIORITY_MAP["artist_refresh"]
DEFAULT_ORCH_VISIBILITY_TIMEOUT_S = 60
DEFAULT_ORCH_HEARTBEAT_S = 20
DEFAULT_ORCH_POLL_INTERVAL_MS = 200
DEFAULT_ORCH_POLL_INTERVAL_MAX_MS = 2000

DEFAULT_EXTERNAL_TIMEOUT_MS = 10_000
DEFAULT_EXTERNAL_RETRY_MAX = 3
DEFAULT_EXTERNAL_BACKOFF_BASE_MS = 250
DEFAULT_EXTERNAL_JITTER_PCT = 20.0

DEFAULT_DOWNLOADS_DIR = "/data/downloads"
DEFAULT_MUSIC_DIR = "/data/music"
DEFAULT_DOWNLOAD_WORKER_CONCURRENCY = 4
DEFAULT_DOWNLOAD_BATCH_MAX_ITEMS = 2_000
DEFAULT_SIZE_STABLE_SECONDS = 30
DEFAULT_DOWNLOAD_MAX_RETRIES = 5
DEFAULT_SLSKD_TIMEOUT_SEC = 300
DEFAULT_MOVE_TEMPLATE = "/data/music/{Artist}/{Year} - {Album}/{Track:02d} {Title}.{ext}"

DEFAULT_WATCHLIST_TIMER_ENABLED = True
DEFAULT_WATCHLIST_TIMER_INTERVAL_S = 900.0
DEFAULT_WATCHLIST_JITTER_PCT = 0.2
DEFAULT_WATCHLIST_SHUTDOWN_GRACE_MS = 2_000
DEFAULT_WATCHLIST_DB_IO_MODE = "thread"
DEFAULT_WATCHLIST_RETRY_BUDGET_PER_ARTIST = 6
DEFAULT_WATCHLIST_COOLDOWN_MINUTES = 15
DEFAULT_ARTIST_POOL_CONCURRENCY = DEFAULT_ORCH_POOL_ARTIST_REFRESH
DEFAULT_ARTIST_MAX_RETRY_PER_ARTIST = DEFAULT_WATCHLIST_RETRY_BUDGET_PER_ARTIST
DEFAULT_ARTIST_COOLDOWN_SECONDS = DEFAULT_WATCHLIST_COOLDOWN_MINUTES * 60
DEFAULT_ARTIST_CACHE_INVALIDATE = False
DEFAULT_ADMIN_API_ENABLED = False
DEFAULT_ADMIN_STALENESS_MAX_MINUTES = 30
DEFAULT_ADMIN_RETRY_BUDGET_MAX = 6
DEFAULT_MATCH_FUZZY_MAX_CANDIDATES = 50
DEFAULT_MATCH_MIN_ARTIST_SIM = 0.6
DEFAULT_MATCH_COMPLETE_THRESHOLD = 0.9
DEFAULT_MATCH_NEARLY_THRESHOLD = 0.8
DEFAULT_RETRY_MAX_ATTEMPTS = 10
DEFAULT_RETRY_BASE_SECONDS = 60.0
DEFAULT_RETRY_JITTER_PCT = 0.2
DEFAULT_RETRY_POLICY_RELOAD_S = 10.0


_CONFIG_TEMPLATE_SECTIONS: tuple[ConfigTemplateSection, ...] = (
    ConfigTemplateSection(
        name="core",
        comment="Core runtime configuration.",
        entries=(
            ConfigTemplateEntry(
                "DATABASE_URL",
                None,
                "SQLite connection string (auto-detected when null).",
            ),
            ConfigTemplateEntry("APP_PORT", DEFAULT_APP_PORT, "Port exposing the API and UI."),
            ConfigTemplateEntry("APP_MODULE", "app.main:app", "ASGI entrypoint."),
            ConfigTemplateEntry("UVICORN_EXTRA_ARGS", "", "Additional uvicorn flags."),
            ConfigTemplateEntry("DB_RESET", 0, "Set to 1 to recreate the SQLite database."),
            ConfigTemplateEntry("APP_ENV", "dev", "Environment tag used in logs."),
            ConfigTemplateEntry("ENVIRONMENT", "dev", "Legacy alias for APP_ENV."),
            ConfigTemplateEntry("HARMONY_PROFILE", DEFAULT_SECURITY_PROFILE, "Security profile."),
            ConfigTemplateEntry("HARMONY_LOG_LEVEL", "INFO", "Logging level."),
            ConfigTemplateEntry("API_BASE_PATH", DEFAULT_API_BASE_PATH, "Public API prefix."),
            ConfigTemplateEntry(
                "REQUEST_ID_HEADER", "X-Request-ID", "Header carrying the request ID."
            ),
            ConfigTemplateEntry("SMOKE_PATH", "/live", "Path probed by smoke checks."),
            ConfigTemplateEntry(
                "UI_LIVE_UPDATES",
                _DEFAULT_UI_LIVE_UPDATES,
                "Live update transport for UI fragments (polling or SSE).",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="paths",
        comment="Filesystem locations managed by the container.",
        entries=(
            ConfigTemplateEntry("DOWNLOADS_DIR", DEFAULT_DOWNLOADS_DIR, "Workspace for downloads."),
            ConfigTemplateEntry("MUSIC_DIR", DEFAULT_MUSIC_DIR, "Final music library directory."),
            ConfigTemplateEntry("ARTWORK_DIR", DEFAULT_ARTWORK_DIR, "Artwork cache directory."),
            ConfigTemplateEntry(
                "OAUTH_STATE_DIR",
                "/data/runtime/oauth_state",
                "Directory storing OAuth state files.",
            ),
            ConfigTemplateEntry(
                "IDEMPOTENCY_SQLITE_PATH",
                str(Path(DEFAULT_DOWNLOADS_DIR) / ".harmony" / "idempotency.db"),
                "SQLite file used for idempotency tracking.",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="security",
        comment="Authentication, authorisation and worker toggles.",
        entries=(
            ConfigTemplateEntry("FEATURE_REQUIRE_AUTH", False, "Require API key authentication."),
            ConfigTemplateEntry("FEATURE_RATE_LIMITING", False, "Enable global rate limiting."),
            ConfigTemplateEntry(
                "FEATURE_ENABLE_LEGACY_ROUTES",
                False,
                "Expose deprecated legacy endpoints.",
            ),
            ConfigTemplateEntry(
                "FEATURE_ADMIN_API", DEFAULT_ADMIN_API_ENABLED, "Enable admin API."
            ),
            ConfigTemplateEntry("HARMONY_API_KEYS", "", "Comma-separated list of API keys."),
            ConfigTemplateEntry(
                "HARMONY_API_KEYS_FILE",
                "",
                "Optional path to file containing API keys (one per line).",
            ),
            ConfigTemplateEntry("HARMONY_DISABLE_WORKERS", False, "Disable background workers."),
            ConfigTemplateEntry("WORKERS_ENABLED", True, "Preferred worker enable flag."),
            ConfigTemplateEntry(
                "WORKER_VISIBILITY_TIMEOUT_S",
                DEFAULT_ORCH_VISIBILITY_TIMEOUT_S,
                "Override worker queue visibility timeout (seconds).",
            ),
            ConfigTemplateEntry(
                "AUTH_ALLOWLIST",
                ",".join(DEFAULT_ALLOWLIST_SUFFIXES),
                "Comma-separated paths bypassing auth checks.",
            ),
            ConfigTemplateEntry(
                "ALLOWED_ORIGINS",
                [],
                "List of allowed CORS origins (empty means allow all).",
            ),
            ConfigTemplateEntry(
                "CORS_ALLOWED_ORIGINS",
                [],
                "Legacy alias for ALLOWED_ORIGINS.",
            ),
            ConfigTemplateEntry("CORS_ALLOWED_HEADERS", "*", "Allowed CORS request headers."),
            ConfigTemplateEntry(
                "CORS_ALLOWED_METHODS",
                "GET,POST,PUT,PATCH,DELETE,OPTIONS",
                "Allowed HTTP methods for CORS preflight.",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="middleware",
        comment="Middleware features and observability toggles.",
        entries=(
            ConfigTemplateEntry("CACHE_ENABLED", True, "Enable HTTP response caching."),
            ConfigTemplateEntry("CACHE_DEFAULT_TTL_S", 30, "Default cache TTL in seconds."),
            ConfigTemplateEntry(
                "CACHE_STALE_WHILE_REVALIDATE_S",
                60,
                "Stale-while-revalidate window in seconds.",
            ),
            ConfigTemplateEntry("CACHE_MAX_ITEMS", 5000, "Maximum cache entries."),
            ConfigTemplateEntry(
                "CACHE_FAIL_OPEN", True, "Serve original responses on cache errors."
            ),
            ConfigTemplateEntry("CACHE_STRATEGY_ETAG", "strong", "ETag calculation strategy."),
            ConfigTemplateEntry(
                "CACHE_WRITE_THROUGH", True, "Invalidate cache entries after writes."
            ),
            ConfigTemplateEntry("CACHE_LOG_EVICTIONS", True, "Log cache eviction events."),
            ConfigTemplateEntry(
                "CACHEABLE_PATHS",
                list(DEFAULT_CACHEABLE_PATH_PATTERNS),
                "Per-route cache rules (pattern|ttl|stale).",
            ),
            ConfigTemplateEntry("GZIP_MIN_SIZE", 1024, "Minimum response size before gzip."),
            ConfigTemplateEntry(
                "HEALTH_DB_TIMEOUT_MS",
                DEFAULT_HEALTH_DB_TIMEOUT_MS,
                "Database readiness timeout in milliseconds.",
            ),
            ConfigTemplateEntry(
                "HEALTH_DEP_TIMEOUT_MS",
                DEFAULT_HEALTH_DEP_TIMEOUT_MS,
                "Dependency readiness timeout in milliseconds.",
            ),
            ConfigTemplateEntry(
                "HEALTH_DEPS",
                [],
                "Additional dependency names probed by readiness checks.",
            ),
            ConfigTemplateEntry(
                "HEALTH_READY_REQUIRE_DB",
                True,
                "Require database connectivity for readiness.",
            ),
            ConfigTemplateEntry(
                "SECRET_VALIDATE_TIMEOUT_MS",
                800,
                "Timeout for runtime secret validation (ms).",
            ),
            ConfigTemplateEntry(
                "SECRET_VALIDATE_MAX_PER_MIN",
                3,
                "Max secret validation attempts per minute.",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="filesystem",
        comment="Container filesystem helpers.",
        entries=(
            ConfigTemplateEntry("PUID", 1000, "Filesystem user ID."),
            ConfigTemplateEntry("PGID", 1000, "Filesystem group ID."),
            ConfigTemplateEntry("UMASK", "007", "Filesystem umask applied at start."),
        ),
    ),
    ConfigTemplateSection(
        name="spotify",
        comment="Spotify integration and free ingest limits.",
        entries=(
            ConfigTemplateEntry("SPOTIFY_CLIENT_ID", "", "Spotify OAuth client ID."),
            ConfigTemplateEntry("SPOTIFY_CLIENT_SECRET", "", "Spotify OAuth client secret."),
            ConfigTemplateEntry(
                "SPOTIFY_REDIRECT_URI",
                "",
                "Optional override for the Spotify redirect URI.",
            ),
            ConfigTemplateEntry(
                "SPOTIFY_SCOPE", DEFAULT_SPOTIFY_SCOPE, "Requested Spotify scopes."
            ),
            ConfigTemplateEntry(
                "SPOTIFY_TIMEOUT_MS",
                15_000,
                "Spotify API timeout in milliseconds.",
            ),
            ConfigTemplateEntry(
                "FREE_IMPORT_MAX_LINES",
                DEFAULT_FREE_IMPORT_MAX_LINES,
                "Max lines parsed from text input.",
            ),
            ConfigTemplateEntry(
                "FREE_IMPORT_MAX_FILE_BYTES",
                DEFAULT_FREE_IMPORT_MAX_FILE_BYTES,
                "Max upload size for free import (bytes).",
            ),
            ConfigTemplateEntry(
                "FREE_IMPORT_MAX_PLAYLIST_LINKS",
                DEFAULT_FREE_IMPORT_MAX_PLAYLIST_LINKS,
                "Max playlist links per request.",
            ),
            ConfigTemplateEntry(
                "FREE_IMPORT_HARD_CAP_MULTIPLIER",
                DEFAULT_FREE_IMPORT_HARD_CAP_MULTIPLIER,
                "Safety multiplier for playlist expansion.",
            ),
            ConfigTemplateEntry(
                "FREE_ACCEPT_USER_URLS",
                False,
                "Allow arbitrary user-submitted URLs in free mode.",
            ),
            ConfigTemplateEntry(
                "FREE_BATCH_SIZE",
                DEFAULT_FREE_INGEST_BATCH_SIZE,
                "Batch size for ingest normalisation in free mode.",
            ),
            ConfigTemplateEntry(
                "FREE_MAX_PLAYLISTS",
                DEFAULT_FREE_INGEST_MAX_PLAYLISTS,
                "Soft cap for playlists per free ingest job.",
            ),
            ConfigTemplateEntry(
                "FREE_MAX_TRACKS_PER_REQUEST",
                DEFAULT_FREE_INGEST_MAX_TRACKS,
                "Hard limit for tracks per request.",
            ),
            ConfigTemplateEntry(
                "BACKFILL_MAX_ITEMS",
                DEFAULT_BACKFILL_MAX_ITEMS,
                "Max items processed per backfill job.",
            ),
            ConfigTemplateEntry(
                "BACKFILL_CACHE_TTL_SEC",
                DEFAULT_BACKFILL_CACHE_TTL,
                "Cache TTL for backfill lookups (seconds).",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="oauth",
        comment="OAuth helper configuration.",
        entries=(
            ConfigTemplateEntry("OAUTH_CALLBACK_PORT", 8888, "Local OAuth callback port."),
            ConfigTemplateEntry(
                "OAUTH_MANUAL_CALLBACK_ENABLE",
                True,
                "Allow manual OAuth completion via API.",
            ),
            ConfigTemplateEntry(
                "OAUTH_SESSION_TTL_MIN",
                10,
                "OAuth session lifetime in minutes.",
            ),
            ConfigTemplateEntry(
                "OAUTH_PUBLIC_HOST_HINT",
                "",
                "Optional hint displayed for remote callbacks.",
            ),
            ConfigTemplateEntry("OAUTH_SPLIT_MODE", False, "Enable split deployment mode."),
            ConfigTemplateEntry(
                "OAUTH_STATE_TTL_SEC",
                600,
                "Lifetime of persisted OAuth state (seconds).",
            ),
            ConfigTemplateEntry(
                "OAUTH_STORE_HASH_CV",
                True,
                "Store hashed PKCE verifier (disable in split mode).",
            ),
            ConfigTemplateEntry(
                "OAUTH_PUBLIC_BASE",
                "/api/v1/oauth",
                "Public base path for OAuth routes.",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="integrations",
        comment="External provider configuration.",
        entries=(
            ConfigTemplateEntry(
                "INTEGRATIONS_ENABLED",
                ["spotify", "slskd"],
                "Comma-separated list of enabled providers.",
            ),
            ConfigTemplateEntry(
                "SLSKD_BASE_URL",
                DEFAULT_SOULSEEK_URL,
                "Preferred Soulseek daemon URL.",
            ),
            ConfigTemplateEntry("SLSKD_URL", "", "Legacy Soulseek URL override."),
            ConfigTemplateEntry("SLSKD_HOST", "", "Legacy Soulseek host override."),
            ConfigTemplateEntry("SLSKD_PORT", "", "Legacy Soulseek port override."),
            ConfigTemplateEntry("SLSKD_API_KEY", "", "Soulseek daemon API key."),
            ConfigTemplateEntry(
                "SLSKD_TIMEOUT_MS",
                DEFAULT_SLSKD_TIMEOUT_MS,
                "Soulseek HTTP timeout in milliseconds.",
            ),
            ConfigTemplateEntry(
                "SLSKD_TIMEOUT_SEC",
                DEFAULT_SLSKD_TIMEOUT_SEC,
                "Soulseek timeout override in seconds.",
            ),
            ConfigTemplateEntry(
                "SLSKD_RETRY_MAX",
                DEFAULT_SLSKD_RETRY_MAX,
                "Retry attempts for Soulseek requests.",
            ),
            ConfigTemplateEntry(
                "SLSKD_RETRY_BACKOFF_BASE_MS",
                DEFAULT_SLSKD_RETRY_BACKOFF_BASE_MS,
                "Backoff base for Soulseek retries (ms).",
            ),
            ConfigTemplateEntry(
                "SLSKD_JITTER_PCT",
                DEFAULT_SLSKD_RETRY_JITTER_PCT,
                "Jitter percentage applied to Soulseek retries.",
            ),
            ConfigTemplateEntry(
                "SLSKD_PREFERRED_FORMATS",
                list(DEFAULT_SLSKD_PREFERRED_FORMATS),
                "Preferred download formats (ordered).",
            ),
            ConfigTemplateEntry(
                "SLSKD_MAX_RESULTS",
                DEFAULT_SLSKD_MAX_RESULTS,
                "Maximum Soulseek search results returned.",
            ),
            ConfigTemplateEntry("MUSIXMATCH_API_KEY", "", "Optional Musixmatch API key."),
        ),
    ),
    ConfigTemplateSection(
        name="external",
        comment="Generic external call policies.",
        entries=(
            ConfigTemplateEntry(
                "EXTERNAL_TIMEOUT_MS",
                DEFAULT_EXTERNAL_TIMEOUT_MS,
                "Default timeout for external providers (ms).",
            ),
            ConfigTemplateEntry(
                "EXTERNAL_RETRY_MAX",
                DEFAULT_EXTERNAL_RETRY_MAX,
                "Retry attempts for external providers.",
            ),
            ConfigTemplateEntry(
                "EXTERNAL_BACKOFF_BASE_MS",
                DEFAULT_EXTERNAL_BACKOFF_BASE_MS,
                "Backoff base for external retries (ms).",
            ),
            ConfigTemplateEntry(
                "EXTERNAL_JITTER_PCT",
                DEFAULT_EXTERNAL_JITTER_PCT,
                "Jitter percentage for external retries.",
            ),
            ConfigTemplateEntry(
                "PROVIDER_MAX_CONCURRENCY",
                DEFAULT_PROVIDER_MAX_CONCURRENCY,
                "Maximum concurrency for provider calls.",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="artwork",
        comment="Artwork and lyrics features.",
        entries=(
            ConfigTemplateEntry("ENABLE_ARTWORK", False, "Enable artwork downloads."),
            ConfigTemplateEntry(
                "ARTWORK_TIMEOUT_SEC",
                DEFAULT_ARTWORK_TIMEOUT,
                "Primary artwork fetch timeout (seconds).",
            ),
            ConfigTemplateEntry(
                "ARTWORK_HTTP_TIMEOUT",
                DEFAULT_ARTWORK_TIMEOUT,
                "HTTP timeout applied to artwork fetches (seconds).",
            ),
            ConfigTemplateEntry(
                "ARTWORK_MAX_BYTES",
                DEFAULT_ARTWORK_MAX_BYTES,
                "Maximum artwork payload size in bytes.",
            ),
            ConfigTemplateEntry(
                "ARTWORK_CONCURRENCY",
                DEFAULT_ARTWORK_CONCURRENCY,
                "Parallel artwork fetchers for API requests.",
            ),
            ConfigTemplateEntry(
                "ARTWORK_WORKER_CONCURRENCY",
                DEFAULT_ARTWORK_CONCURRENCY,
                "Parallelism for the artwork worker.",
            ),
            ConfigTemplateEntry(
                "ARTWORK_MIN_EDGE",
                DEFAULT_ARTWORK_MIN_EDGE,
                "Minimum artwork resolution edge in pixels.",
            ),
            ConfigTemplateEntry(
                "ARTWORK_MIN_BYTES",
                DEFAULT_ARTWORK_MIN_BYTES,
                "Minimum payload size to accept (bytes).",
            ),
            ConfigTemplateEntry("ARTWORK_FALLBACK_ENABLED", False, "Enable fallback provider."),
            ConfigTemplateEntry(
                "ARTWORK_FALLBACK_PROVIDER",
                "musicbrainz",
                "Fallback artwork provider name.",
            ),
            ConfigTemplateEntry(
                "ARTWORK_FALLBACK_TIMEOUT_SEC",
                DEFAULT_ARTWORK_FALLBACK_TIMEOUT,
                "Fallback provider timeout (seconds).",
            ),
            ConfigTemplateEntry(
                "ARTWORK_FALLBACK_MAX_BYTES",
                DEFAULT_ARTWORK_FALLBACK_MAX_BYTES,
                "Fallback provider max payload (bytes).",
            ),
            ConfigTemplateEntry(
                "ARTWORK_POST_PROCESSING_ENABLED", False, "Enable post-processing."
            ),
            ConfigTemplateEntry(
                "ARTWORK_POST_PROCESSORS",
                [],
                "Commands executed during post-processing.",
            ),
            ConfigTemplateEntry("ENABLE_LYRICS", False, "Enable automatic lyrics worker."),
        ),
    ),
    ConfigTemplateSection(
        name="ingest",
        comment="Ingest pipeline and matching limits.",
        entries=(
            ConfigTemplateEntry(
                "INGEST_BATCH_SIZE",
                DEFAULT_INGEST_BATCH_SIZE,
                "Batch size for ingest queue submissions.",
            ),
            ConfigTemplateEntry(
                "INGEST_MAX_PENDING_JOBS",
                DEFAULT_INGEST_MAX_PENDING_JOBS,
                "Max pending ingest jobs before backpressure.",
            ),
            ConfigTemplateEntry(
                "FEATURE_MATCHING_EDITION_AWARE",
                True,
                "Enable edition-aware matching heuristics.",
            ),
            ConfigTemplateEntry(
                "MATCH_FUZZY_MAX_CANDIDATES",
                DEFAULT_MATCH_FUZZY_MAX_CANDIDATES,
                "Fuzzy matching candidate limit.",
            ),
            ConfigTemplateEntry(
                "MATCH_MIN_ARTIST_SIM",
                DEFAULT_MATCH_MIN_ARTIST_SIM,
                "Minimum artist similarity threshold.",
            ),
            ConfigTemplateEntry(
                "MATCH_COMPLETE_THRESHOLD",
                DEFAULT_MATCH_COMPLETE_THRESHOLD,
                "Confidence threshold for complete discography.",
            ),
            ConfigTemplateEntry(
                "MATCH_NEARLY_THRESHOLD",
                DEFAULT_MATCH_NEARLY_THRESHOLD,
                "Confidence threshold for nearly complete state.",
            ),
            ConfigTemplateEntry(
                "MATCHING_WORKER_BATCH_SIZE",
                5,
                "Matching jobs processed per worker iteration.",
            ),
            ConfigTemplateEntry(
                "MATCHING_CONFIDENCE_THRESHOLD",
                0.65,
                "Minimum score to accept a candidate.",
            ),
            ConfigTemplateEntry("SEARCH_MAX_LIMIT", 100, "Maximum search results returned."),
        ),
    ),
    ConfigTemplateSection(
        name="hdm",
        comment="Harmony Download Manager configuration.",
        entries=(
            ConfigTemplateEntry(
                "WORKER_CONCURRENCY",
                DEFAULT_DOWNLOAD_WORKER_CONCURRENCY,
                "HDM worker concurrency.",
            ),
            ConfigTemplateEntry(
                "BATCH_MAX_ITEMS",
                DEFAULT_DOWNLOAD_BATCH_MAX_ITEMS,
                "Maximum queue batch size for HDM.",
            ),
            ConfigTemplateEntry(
                "SIZE_STABLE_SEC",
                DEFAULT_SIZE_STABLE_SECONDS,
                "Seconds to consider download size stable.",
            ),
            ConfigTemplateEntry(
                "MAX_RETRIES",
                DEFAULT_DOWNLOAD_MAX_RETRIES,
                "Maximum HDM retries per job.",
            ),
            ConfigTemplateEntry(
                "MOVE_TEMPLATE", DEFAULT_MOVE_TEMPLATE, "Template for moving completed files."
            ),
            ConfigTemplateEntry(
                "IDEMPOTENCY_BACKEND",
                DEFAULT_IDEMPOTENCY_BACKEND,
                "Backend used for HDM idempotency tracking.",
            ),
            ConfigTemplateEntry(
                "SLSKD_TIMEOUT_SEC",
                DEFAULT_SLSKD_TIMEOUT_SEC,
                "Timeout for Soulseek transfers (seconds).",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="watchlist",
        comment="Watchlist worker and orchestrator settings.",
        entries=(
            ConfigTemplateEntry(
                "WATCHLIST_MAX_CONCURRENCY",
                DEFAULT_WATCHLIST_MAX_CONCURRENCY,
                "Maximum concurrent watchlist jobs.",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_MAX_PER_TICK",
                DEFAULT_WATCHLIST_MAX_PER_TICK,
                "Maximum watchlist jobs processed per tick.",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_SPOTIFY_TIMEOUT_MS",
                DEFAULT_WATCHLIST_SPOTIFY_TIMEOUT_MS,
                "Spotify timeout for watchlist jobs (ms).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS",
                DEFAULT_WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS,
                "Soulseek search timeout for watchlist jobs (ms).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_TICK_BUDGET_MS",
                DEFAULT_WATCHLIST_TICK_BUDGET_MS,
                "Time budget per watchlist tick (ms).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_BACKOFF_BASE_MS",
                DEFAULT_WATCHLIST_BACKOFF_BASE_MS,
                "Base delay for watchlist retries (ms).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_RETRY_MAX",
                DEFAULT_WATCHLIST_RETRY_MAX,
                "Maximum watchlist retry attempts.",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_JITTER_PCT",
                DEFAULT_WATCHLIST_JITTER_PCT,
                "Jitter percentage for watchlist retries.",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_SHUTDOWN_GRACE_MS",
                DEFAULT_WATCHLIST_SHUTDOWN_GRACE_MS,
                "Shutdown grace period for watchlist worker (ms).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_DB_IO_MODE",
                DEFAULT_WATCHLIST_DB_IO_MODE,
                "Database IO mode for watchlist worker (thread/async).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_RETRY_BUDGET_PER_ARTIST",
                DEFAULT_WATCHLIST_RETRY_BUDGET_PER_ARTIST,
                "Retry budget per artist before cooldown.",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_COOLDOWN_MINUTES",
                DEFAULT_WATCHLIST_COOLDOWN_MINUTES,
                "Cooldown between artist retries (minutes).",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_INTERVAL", None, "Optional override for watchlist interval."
            ),
            ConfigTemplateEntry(
                "WATCHLIST_TIMER_ENABLED",
                DEFAULT_WATCHLIST_TIMER_ENABLED,
                "Enable periodic watchlist timer.",
            ),
            ConfigTemplateEntry(
                "WATCHLIST_TIMER_INTERVAL_S",
                DEFAULT_WATCHLIST_TIMER_INTERVAL_S,
                "Interval for watchlist timer (seconds).",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="orchestrator",
        comment="Queue orchestrator limits and priorities.",
        entries=(
            ConfigTemplateEntry(
                "WORKERS_ENABLED",
                True,
                "Enable orchestrator workers (duplicate for clarity).",
            ),
            ConfigTemplateEntry(
                "ORCH_GLOBAL_CONCURRENCY",
                DEFAULT_ORCH_GLOBAL_CONCURRENCY,
                "Global concurrency for orchestrator workers.",
            ),
            ConfigTemplateEntry(
                "ORCH_POOL_SYNC",
                DEFAULT_ORCH_POOL_SYNC,
                "Sync worker pool size.",
            ),
            ConfigTemplateEntry(
                "ORCH_POOL_MATCHING",
                DEFAULT_ORCH_POOL_MATCHING,
                "Matching worker pool size.",
            ),
            ConfigTemplateEntry(
                "ORCH_POOL_RETRY",
                DEFAULT_ORCH_POOL_RETRY,
                "Retry worker pool size.",
            ),
            ConfigTemplateEntry(
                "ORCH_POOL_ARTIST_REFRESH",
                DEFAULT_ORCH_POOL_ARTIST_REFRESH,
                "Artist refresh pool size.",
            ),
            ConfigTemplateEntry(
                "ORCH_POOL_ARTIST_DELTA",
                DEFAULT_ORCH_POOL_ARTIST_DELTA,
                "Artist delta pool size.",
            ),
            ConfigTemplateEntry(
                "ORCH_VISIBILITY_TIMEOUT_S",
                DEFAULT_ORCH_VISIBILITY_TIMEOUT_S,
                "Queue visibility timeout (seconds).",
            ),
            ConfigTemplateEntry(
                "ORCH_HEARTBEAT_S",
                DEFAULT_ORCH_HEARTBEAT_S,
                "Worker heartbeat interval (seconds).",
            ),
            ConfigTemplateEntry(
                "ORCH_POLL_INTERVAL_MS",
                DEFAULT_ORCH_POLL_INTERVAL_MS,
                "Minimum queue poll interval (ms).",
            ),
            ConfigTemplateEntry(
                "ORCH_POLL_INTERVAL_MAX_MS",
                DEFAULT_ORCH_POLL_INTERVAL_MAX_MS,
                "Maximum queue poll interval (ms).",
            ),
            ConfigTemplateEntry(
                "ORCH_PRIORITY_JSON",
                "",
                "JSON mapping overriding queue priorities.",
            ),
            ConfigTemplateEntry(
                "ORCH_PRIORITY_CSV",
                "",
                "CSV mapping overriding queue priorities.",
            ),
        ),
    ),
    ConfigTemplateSection(
        name="retry",
        comment="Retry policy defaults for orchestrator jobs.",
        entries=(
            ConfigTemplateEntry(
                "RETRY_MAX_ATTEMPTS",
                DEFAULT_RETRY_MAX_ATTEMPTS,
                "Maximum retry attempts per job.",
            ),
            ConfigTemplateEntry(
                "RETRY_BASE_SECONDS",
                DEFAULT_RETRY_BASE_SECONDS,
                "Base delay between retries (seconds).",
            ),
            ConfigTemplateEntry(
                "RETRY_JITTER_PCT",
                DEFAULT_RETRY_JITTER_PCT,
                "Jitter fraction applied to retries.",
            ),
            ConfigTemplateEntry(
                "RETRY_SCAN_BATCH_LIMIT",
                100,
                "Number of queued retries scanned per sweep.",
            ),
            ConfigTemplateEntry(
                "RETRY_SCAN_INTERVAL_SEC",
                60.0,
                "Interval between retry scans (seconds).",
            ),
            ConfigTemplateEntry(
                "RETRY_ARTIST_SYNC_MAX_ATTEMPTS",
                10,
                "Max retry attempts for artist sync jobs.",
            ),
            ConfigTemplateEntry(
                "RETRY_ARTIST_SYNC_BASE_SECONDS",
                60,
                "Base delay for artist sync retries (seconds).",
            ),
            ConfigTemplateEntry(
                "RETRY_ARTIST_SYNC_JITTER_PCT",
                0.2,
                "Jitter fraction for artist sync retries.",
            ),
            ConfigTemplateEntry(
                "RETRY_ARTIST_SYNC_TIMEOUT_SECONDS",
                None,
                "Optional timeout for artist sync retry cycle (seconds).",
            ),
        ),
    ),
)


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    resolved = _coerce_int(value, default=default)
    if minimum is not None:
        resolved = max(minimum, resolved)
    if maximum is not None:
        resolved = min(maximum, resolved)
    return resolved


def _parse_list(value: str | None) -> list[str]:
    if value is None:
        return []
    candidates = value.replace("\n", ",").split(",")
    return [item.strip() for item in candidates if item.strip()]


def _bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        resolved = default
    if minimum is not None:
        resolved = max(minimum, resolved)
    if maximum is not None:
        resolved = min(maximum, resolved)
    return resolved


_SQLITE_ALLOWED_PREFIXES = (
    "sqlite",
    "sqlite+aiosqlite",
    "sqlite+pysqlite",
)


def _normalise_sqlite_database_url(candidate: str | None, *, default_hint: str) -> str:
    from app.errors import ValidationAppError

    value = (candidate or "").strip()
    if not value:
        raise ValidationAppError(
            "DATABASE_URL must be configured with a sqlite+ connection string, "
            f"for example {default_hint}.",
            meta={"field": "DATABASE_URL"},
        )

    try:
        url = make_url(value)
    except (ArgumentError, ValueError) as exc:  # pragma: no cover - defensive guard
        raise ValidationAppError(
            "DATABASE_URL is not a valid sqlite+ SQLAlchemy connection string.",
            meta={"field": "DATABASE_URL"},
        ) from exc

    driver = url.drivername.lower()
    if not any(driver.startswith(prefix) for prefix in _SQLITE_ALLOWED_PREFIXES):
        raise ValidationAppError(
            (
                "DATABASE_URL must use a sqlite+aiosqlite:/// or sqlite+pysqlite:/// "
                "connection string."
            ),
            meta={"field": "DATABASE_URL"},
        )

    return url.render_as_string(hide_password=False)


def _default_database_url_for_profile(profile: str) -> str:
    if profile == "prod" or profile == "staging":
        return DEFAULT_DB_URL_PROD
    if profile == "test":
        return DEFAULT_DB_URL_TEST
    return DEFAULT_DB_URL_DEV


def _resolve_database_url(env: Mapping[str, Any], explicit: str | None) -> str:
    profile, _flags = _resolve_environment_profile(env)
    default_url = _default_database_url_for_profile(profile)
    if explicit is not None:
        return _normalise_sqlite_database_url(explicit, default_hint=default_url)
    candidate = env.get("DATABASE_URL")
    if candidate:
        return _normalise_sqlite_database_url(str(candidate), default_hint=default_url)
    return _normalise_sqlite_database_url(default_url, default_hint=default_url)


def _resolve_sync_database_url(database_url: str) -> str:
    url = make_url(database_url)
    driver = url.drivername.lower()
    if driver == "sqlite+aiosqlite" or driver == "sqlite":
        url = url.set(drivername="sqlite+pysqlite")
    return url.render_as_string(hide_password=False)


def _parse_bool_override(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    logger.warning("Ignoring invalid boolean override value: %s", value)
    return None


def _parse_optional_int(
    value: Any,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return None
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid integer override value: %s", value)
        return None
    if minimum is not None and resolved < minimum:
        logger.warning("Integer override %s below minimum %s; clamping", value, minimum)
        resolved = minimum
    if maximum is not None and resolved > maximum:
        resolved = maximum
    return resolved


def _parse_optional_float(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid float override value: %s", value)
        return None
    if minimum is not None and resolved < minimum:
        logger.warning("Float override %s below minimum %s; clamping", value, minimum)
        resolved = minimum
    if maximum is not None and resolved > maximum:
        resolved = maximum
    return resolved


def _parse_enabled_providers(value: str | None) -> tuple[str, ...]:
    if not value:
        return ("spotify", "slskd")
    items = [entry.strip().lower() for entry in value.replace("\n", ",").split(",")]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)
    return tuple(deduplicated or ("spotify", "slskd"))


def _parse_dependency_names(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    items = [entry.strip().lower() for entry in value.replace("\n", ",").split(",")]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)
    return tuple(deduplicated)


def _parse_provider_timeouts(env: Mapping[str, str | None]) -> dict[str, int]:
    defaults: dict[str, int] = {
        "spotify": 15000,
        "slskd": DEFAULT_SLSKD_TIMEOUT_MS,
    }
    for key, provider in (
        ("SPOTIFY_TIMEOUT_MS", "spotify"),
        ("SLSKD_TIMEOUT_MS", "slskd"),
    ):
        raw = env.get(key)
        if raw is None:
            continue
        try:
            defaults[provider] = max(200, int(raw))
        except (TypeError, ValueError):
            continue
    return defaults


def _parse_jitter_value(value: Any, *, default_pct: float) -> float:
    resolved = default_pct
    if value is not None:
        try:
            resolved = float(value)
        except (TypeError, ValueError):
            resolved = default_pct
    if resolved < 0:
        return 0.0
    if resolved <= 1:
        return resolved
    return resolved / 100.0


def _parse_priority_map(env: Mapping[str, Any]) -> dict[str, int]:
    default_map = dict(DEFAULT_ORCH_PRIORITY_MAP)
    raw_json = env.get("ORCH_PRIORITY_JSON")
    if raw_json:
        mapping = parse_priority_map(str(raw_json), {})
        filtered = {key: value for key, value in mapping.items() if key in default_map}
        if filtered:
            return filtered
    raw_csv = env.get("ORCH_PRIORITY_CSV")
    if raw_csv:
        mapping = parse_priority_map(str(raw_csv), {})
        filtered = {key: value for key, value in mapping.items() if key in default_map}
        if filtered:
            return filtered
    return default_map


def _load_provider_profiles(
    env: Mapping[str, Any], default_policy: ExternalCallPolicy
) -> dict[str, ProviderProfile]:
    profiles: dict[str, ProviderProfile] = {}
    candidates = {"spotify", "slskd"}
    for provider in candidates:
        prefix = f"PROVIDER_{provider.upper()}"
        keys = {
            "timeout": f"{prefix}_TIMEOUT_MS",
            "retry": f"{prefix}_RETRY_MAX",
            "backoff": f"{prefix}_BACKOFF_BASE_MS",
            "jitter": f"{prefix}_JITTER_PCT",
        }
        if not any(key in env for key in keys.values()):
            continue
        policy = ExternalCallPolicy(
            timeout_ms=_bounded_int(
                env.get(keys["timeout"]),
                default=default_policy.timeout_ms,
                minimum=100,
            ),
            retry_max=_bounded_int(
                env.get(keys["retry"]),
                default=default_policy.retry_max,
                minimum=0,
            ),
            backoff_base_ms=_bounded_int(
                env.get(keys["backoff"]),
                default=default_policy.backoff_base_ms,
                minimum=1,
            ),
            jitter_pct=_parse_jitter_value(
                env.get(keys["jitter"]),
                default_pct=default_policy.jitter_pct,
            ),
        )
        profiles[provider] = ProviderProfile(name=provider, policy=policy)
    return profiles


def _resolve_environment_profile(env: Mapping[str, Any]) -> tuple[str, dict[str, bool]]:
    raw = str(env.get("APP_ENV") or env.get("ENVIRONMENT") or "").strip()
    if not raw and env.get("PYTEST_CURRENT_TEST"):
        raw = "test"
    normalized = raw.lower()
    aliases = {
        "development": "dev",
        "local": "dev",
        "production": "prod",
        "live": "prod",
        "stage": "staging",
    }
    normalized = aliases.get(normalized, normalized)
    valid = {"dev", "staging", "prod", "test"}
    if normalized not in valid:
        if normalized:
            logger.warning("Unknown APP_ENV value %s; defaulting to dev", raw)
        normalized = "dev"
    flags = {
        "is_dev": normalized == "dev",
        "is_test": normalized == "test",
        "is_staging": normalized == "staging",
        "is_prod": normalized == "prod",
    }
    return normalized, flags


def _load_environment_config(env: Mapping[str, Any]) -> EnvironmentConfig:
    profile, flags = _resolve_environment_profile(env)
    workers_enabled_raw = env.get("WORKERS_ENABLED")
    workers_enabled_override = _parse_bool_override(workers_enabled_raw)
    disable_workers = _as_bool(
        (str(env.get("HARMONY_DISABLE_WORKERS")) if "HARMONY_DISABLE_WORKERS" in env else None),
        default=False,
    )
    visibility_override = _parse_optional_int(env.get("WORKER_VISIBILITY_TIMEOUT_S"), minimum=5)
    watchlist_interval = _parse_optional_float(env.get("WATCHLIST_INTERVAL"))
    watchlist_timer_enabled = _parse_bool_override(env.get("WATCHLIST_TIMER_ENABLED"))

    workers = WorkerEnvironmentConfig(
        disable_workers=disable_workers,
        enabled_override=workers_enabled_override,
        enabled_raw=(str(workers_enabled_raw) if workers_enabled_raw is not None else None),
        visibility_timeout_s=visibility_override,
        watchlist_interval_s=watchlist_interval,
        watchlist_timer_enabled=watchlist_timer_enabled,
    )

    return EnvironmentConfig(
        profile=profile,
        is_dev=flags["is_dev"],
        is_test=flags["is_test"],
        is_staging=flags["is_staging"],
        is_prod=flags["is_prod"],
        workers=workers,
    )


def _load_retry_policy(env: Mapping[str, Any]) -> RetryPolicyConfig:
    max_attempts = _bounded_int(
        env.get("RETRY_MAX_ATTEMPTS"),
        default=DEFAULT_RETRY_MAX_ATTEMPTS,
        minimum=1,
    )
    base_seconds = _bounded_float(
        env.get("RETRY_BASE_SECONDS"),
        default=DEFAULT_RETRY_BASE_SECONDS,
        minimum=1e-3,
    )
    jitter_pct = _parse_jitter_value(
        env.get("RETRY_JITTER_PCT"),
        default_pct=DEFAULT_RETRY_JITTER_PCT,
    )
    return RetryPolicyConfig(
        max_attempts=max_attempts,
        base_seconds=base_seconds,
        jitter_pct=jitter_pct,
    )


def resolve_retry_policy(env: Mapping[str, Any] | None = None) -> RetryPolicyConfig:
    """Load the retry policy configuration from the provided environment."""

    env_map: Mapping[str, Any] = env or get_runtime_env()
    return _load_retry_policy(env_map)


settings = Settings.load()

log_event(
    logger,
    "config.loaded",
    component="config",
    status="ok",
    meta={
        "orchestrator": {
            "workers_enabled": settings.orchestrator.workers_enabled,
            "global_concurrency": settings.orchestrator.global_concurrency,
            "poll_interval_ms": settings.orchestrator.poll_interval_ms,
            "poll_interval_max_ms": settings.orchestrator.poll_interval_max_ms,
            "visibility_timeout_s": settings.orchestrator.visibility_timeout_s,
        },
        "external": {
            "timeout_ms": settings.external.timeout_ms,
            "retry_max": settings.external.retry_max,
            "backoff_base_ms": settings.external.backoff_base_ms,
            "jitter_pct": settings.external.jitter_pct,
        },
        "watchlist_timer": {
            "enabled": settings.watchlist_timer.enabled,
            "interval_s": settings.watchlist_timer.interval_s,
        },
        "provider_profiles": sorted(settings.provider_profiles.keys()),
        "retry_policy": {
            "max_attempts": settings.retry_policy.max_attempts,
            "base_seconds": settings.retry_policy.base_seconds,
            "jitter_pct": settings.retry_policy.jitter_pct,
        },
    },
)


def _read_api_keys_from_file(path: str) -> list[str]:
    if not path:
        return []
    try:
        contents = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in contents.splitlines() if line.strip()]


def _deduplicate_preserve_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _parse_optional_duration(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _parse_cache_rules(values: Iterable[str]) -> tuple[CacheRule, ...]:
    rules: list[CacheRule] = []
    for raw_value in values:
        if not raw_value:
            continue
        segments = raw_value.split("|")
        pattern = segments[0].strip()
        if not pattern:
            continue
        ttl = None
        stale = None
        if len(segments) > 1:
            ttl = _parse_optional_duration(segments[1].strip() or None)
        if len(segments) > 2:
            stale = _parse_optional_duration(segments[2].strip() or None)
        rules.append(CacheRule(pattern=pattern, ttl=ttl, stale_while_revalidate=stale))
    return tuple(rules)


def _normalise_prefix(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    if cleaned != "/":
        cleaned = cleaned.rstrip("/")
    return cleaned


def _normalise_base_path(value: str | None) -> str:
    candidate = value if value is not None else DEFAULT_API_BASE_PATH
    normalized = _normalise_prefix(candidate)
    if normalized == "":
        return ""
    return normalized


def _compose_allowlist_entry(base_path: str, suffix: str) -> str:
    normalized_suffix = _normalise_prefix(suffix)
    if not normalized_suffix or normalized_suffix == "/":
        return base_path or "/"
    if not base_path or base_path == "/":
        return normalized_suffix
    return f"{base_path}{normalized_suffix}"


def _as_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_matching_config(env: Mapping[str, Any] | None = None) -> MatchingConfig:
    """Return configuration values that control the matching engine."""

    env = env or get_runtime_env()
    edition_aware = _as_bool(
        _env_value(env, "FEATURE_MATCHING_EDITION_AWARE"),
        default=True,
    )
    fuzzy_max = max(
        5,
        _as_int(
            _env_value(env, "MATCH_FUZZY_MAX_CANDIDATES"),
            default=DEFAULT_MATCH_FUZZY_MAX_CANDIDATES,
        ),
    )
    min_artist = max(
        0.0,
        min(
            1.0,
            _as_float(
                _env_value(env, "MATCH_MIN_ARTIST_SIM"),
                default=DEFAULT_MATCH_MIN_ARTIST_SIM,
            ),
        ),
    )
    complete = max(
        0.0,
        min(
            1.0,
            _as_float(
                _env_value(env, "MATCH_COMPLETE_THRESHOLD"),
                default=DEFAULT_MATCH_COMPLETE_THRESHOLD,
            ),
        ),
    )
    nearly = max(
        0.0,
        min(
            complete,
            _as_float(
                _env_value(env, "MATCH_NEARLY_THRESHOLD"),
                default=DEFAULT_MATCH_NEARLY_THRESHOLD,
            ),
        ),
    )
    return MatchingConfig(
        edition_aware=edition_aware,
        fuzzy_max_candidates=fuzzy_max,
        min_artist_similarity=min_artist,
        complete_threshold=complete,
        nearly_threshold=nearly,
    )


def _load_settings_from_db(
    keys: Iterable[str],
    *,
    database_url: str | None = None,
    env: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    """Fetch selected settings from the database."""

    runtime_env = env or get_runtime_env()
    database_url = _resolve_database_url(runtime_env, database_url)
    sync_database_url = _resolve_sync_database_url(database_url)

    try:
        engine = create_engine(sync_database_url)
    except SQLAlchemyError:
        return {}

    settings: dict[str, str | None] = {}
    try:
        with engine.connect() as connection:
            for key in keys:
                try:
                    row = connection.execute(
                        text("SELECT value FROM settings WHERE key = :key LIMIT 1"),
                        {"key": key},
                    ).first()
                except SQLAlchemyError:
                    return {}

                if row is not None:
                    # Preserve keys found in the database, even if the value is NULL.
                    settings[key] = row[0]
    except SQLAlchemyError:
        return {}
    finally:
        engine.dispose()

    return settings


def get_setting(
    key: str,
    *,
    database_url: str | None = None,
    env: Mapping[str, Any] | None = None,
) -> str | None:
    """Return a single setting value from the database if available."""

    settings = _load_settings_from_db([key], database_url=database_url, env=env)
    return settings.get(key)


def _resolve_setting(
    key: str,
    *,
    db_settings: Mapping[str, str | None],
    fallback: str | None,
) -> str | None:
    if key in db_settings:
        value = db_settings[key]
        return fallback if value is None else value
    return fallback


def _legacy_slskd_url(env: Mapping[str, Any]) -> str | None:
    host = (_env_value(env, "SLSKD_HOST") or "").strip()
    port = (_env_value(env, "SLSKD_PORT") or "").strip()

    if not host:
        return None

    if not port:
        port = str(DEFAULT_SOULSEEK_PORT)

    return f"http://{host}:{port}"


def load_config(runtime_env: Mapping[str, Any] | None = None) -> AppConfig:
    """Load application configuration prioritising database backed settings."""

    env = runtime_env or get_runtime_env()
    database_url = _resolve_database_url(env, None)

    config_keys = [
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "SLSKD_URL",
        "SLSKD_API_KEY",
        "ENABLE_ARTWORK",
        "ENABLE_LYRICS",
    ]
    db_settings = dict(_load_settings_from_db(config_keys, database_url=database_url, env=env))
    legacy_slskd_url = _legacy_slskd_url(env)
    if legacy_slskd_url is not None:
        db_settings.pop("SLSKD_URL", None)

    environment_config = _load_environment_config(env)

    oauth_callback_port = _bounded_int(
        _env_value(env, "OAUTH_CALLBACK_PORT"),
        default=8888,
        minimum=1,
        maximum=65535,
    )
    oauth_redirect_uri = f"http://127.0.0.1:{oauth_callback_port}/callback"
    oauth_manual_enabled = _as_bool(_env_value(env, "OAUTH_MANUAL_CALLBACK_ENABLE"), default=True)
    oauth_session_ttl_min = max(
        1,
        _as_int(
            _env_value(env, "OAUTH_SESSION_TTL_MIN"),
            default=10,
        ),
    )
    oauth_public_host_hint = (_env_value(env, "OAUTH_PUBLIC_HOST_HINT") or "").strip() or None
    oauth_split_mode = _as_bool(_env_value(env, "OAUTH_SPLIT_MODE"), default=False)
    oauth_state_dir = (
        _env_value(env, "OAUTH_STATE_DIR") or "/data/runtime/oauth_state"
    ).strip() or "/data/runtime/oauth_state"
    oauth_state_ttl_seconds = max(
        1,
        _as_int(
            _env_value(env, "OAUTH_STATE_TTL_SEC"),
            default=oauth_session_ttl_min * 60,
        ),
    )
    oauth_store_hash_cv = _as_bool(_env_value(env, "OAUTH_STORE_HASH_CV"), default=True)

    spotify = SpotifyConfig(
        client_id=_resolve_setting(
            "SPOTIFY_CLIENT_ID",
            db_settings=db_settings,
            fallback=_env_value(env, "SPOTIFY_CLIENT_ID"),
        ),
        client_secret=_resolve_setting(
            "SPOTIFY_CLIENT_SECRET",
            db_settings=db_settings,
            fallback=_env_value(env, "SPOTIFY_CLIENT_SECRET"),
        ),
        redirect_uri=_resolve_setting(
            "SPOTIFY_REDIRECT_URI",
            db_settings=db_settings,
            fallback=_env_value(env, "SPOTIFY_REDIRECT_URI"),
        ),
        scope=_env_value(env, "SPOTIFY_SCOPE") or DEFAULT_SPOTIFY_SCOPE,
        free_import_max_lines=max(
            1,
            _as_int(
                _env_value(env, "FREE_IMPORT_MAX_LINES"),
                default=DEFAULT_FREE_IMPORT_MAX_LINES,
            ),
        ),
        free_import_max_file_bytes=max(
            1,
            _as_int(
                _env_value(env, "FREE_IMPORT_MAX_FILE_BYTES"),
                default=DEFAULT_FREE_IMPORT_MAX_FILE_BYTES,
            ),
        ),
        free_import_max_playlist_links=max(
            1,
            _as_int(
                _env_value(env, "FREE_IMPORT_MAX_PLAYLIST_LINKS"),
                default=DEFAULT_FREE_IMPORT_MAX_PLAYLIST_LINKS,
            ),
        ),
        free_import_hard_cap_multiplier=max(
            1,
            _as_int(
                _env_value(env, "FREE_IMPORT_HARD_CAP_MULTIPLIER"),
                default=DEFAULT_FREE_IMPORT_HARD_CAP_MULTIPLIER,
            ),
        ),
        free_accept_user_urls=_as_bool(
            _env_value(env, "FREE_ACCEPT_USER_URLS"),
            default=False,
        ),
        backfill_max_items=max(
            1,
            _as_int(
                _env_value(env, "BACKFILL_MAX_ITEMS"),
                default=DEFAULT_BACKFILL_MAX_ITEMS,
            ),
        ),
        backfill_cache_ttl_seconds=max(
            60,
            _as_int(
                _env_value(env, "BACKFILL_CACHE_TTL_SEC"),
                default=DEFAULT_BACKFILL_CACHE_TTL,
            ),
        ),
    )
    if not (spotify.redirect_uri or "").strip():
        spotify.redirect_uri = oauth_redirect_uri

    soulseek_base_env = (
        _env_value(env, "SLSKD_BASE_URL")
        or _env_value(env, "SLSKD_URL")
        or legacy_slskd_url
        or DEFAULT_SOULSEEK_URL
    )
    timeout_ms = max(
        200,
        _as_int(
            _env_value(env, "SLSKD_TIMEOUT_MS"),
            default=DEFAULT_SLSKD_TIMEOUT_MS,
        ),
    )
    retry_max = max(
        0,
        _as_int(
            _env_value(env, "SLSKD_RETRY_MAX"),
            default=DEFAULT_SLSKD_RETRY_MAX,
        ),
    )
    retry_backoff_base_ms = max(
        50,
        _as_int(
            _env_value(env, "SLSKD_RETRY_BACKOFF_BASE_MS"),
            default=DEFAULT_SLSKD_RETRY_BACKOFF_BASE_MS,
        ),
    )
    retry_jitter_pct_raw = _as_float(
        _env_value(env, "SLSKD_JITTER_PCT"), default=DEFAULT_SLSKD_RETRY_JITTER_PCT
    )
    retry_jitter_pct = min(100.0, max(0.0, retry_jitter_pct_raw))
    preferred_formats_list = _parse_list(_env_value(env, "SLSKD_PREFERRED_FORMATS"))
    if not preferred_formats_list:
        preferred_formats_list = list(DEFAULT_SLSKD_PREFERRED_FORMATS)
    preferred_formats = tuple(preferred_formats_list)
    max_results = max(
        1,
        _as_int(
            _env_value(env, "SLSKD_MAX_RESULTS"),
            default=DEFAULT_SLSKD_MAX_RESULTS,
        ),
    )
    soulseek = SoulseekConfig(
        base_url=_resolve_setting(
            "SLSKD_URL",
            db_settings=db_settings,
            fallback=soulseek_base_env,
        )
        or DEFAULT_SOULSEEK_URL,
        api_key=_resolve_setting(
            "SLSKD_API_KEY",
            db_settings=db_settings,
            fallback=_env_value(env, "SLSKD_API_KEY"),
        ),
        timeout_ms=timeout_ms,
        retry_max=retry_max,
        retry_backoff_base_ms=retry_backoff_base_ms,
        retry_jitter_pct=retry_jitter_pct,
        preferred_formats=preferred_formats,
        max_results=max_results,
    )

    logging = LoggingConfig(level=_env_value(env, "HARMONY_LOG_LEVEL") or "INFO")
    database = DatabaseConfig(url=database_url)

    artwork_dir = _env_value(env, "ARTWORK_DIR") or _env_value(env, "HARMONY_ARTWORK_DIR")
    timeout_value = _env_value(env, "ARTWORK_HTTP_TIMEOUT") or _env_value(
        env, "ARTWORK_TIMEOUT_SEC"
    )
    concurrency_value = _env_value(env, "ARTWORK_WORKER_CONCURRENCY") or _env_value(
        env, "ARTWORK_CONCURRENCY"
    )
    min_edge_value = _env_value(env, "ARTWORK_MIN_EDGE")
    min_bytes_value = _env_value(env, "ARTWORK_MIN_BYTES")
    post_processors_raw = _env_value(env, "ARTWORK_POST_PROCESSORS")
    if post_processors_raw:
        processor_entries = post_processors_raw.replace("\n", ",").split(",")
        post_processors = tuple(entry.strip() for entry in processor_entries if entry.strip())
    else:
        post_processors = ()

    artwork_config = ArtworkConfig(
        directory=(artwork_dir or DEFAULT_ARTWORK_DIR),
        timeout_seconds=_as_float(timeout_value, default=DEFAULT_ARTWORK_TIMEOUT),
        max_bytes=_as_int(_env_value(env, "ARTWORK_MAX_BYTES"), default=DEFAULT_ARTWORK_MAX_BYTES),
        concurrency=max(
            1,
            _as_int(
                concurrency_value,
                default=DEFAULT_ARTWORK_CONCURRENCY,
            ),
        ),
        min_edge=_as_int(min_edge_value, default=DEFAULT_ARTWORK_MIN_EDGE),
        min_bytes=_as_int(min_bytes_value, default=DEFAULT_ARTWORK_MIN_BYTES),
        fallback=ArtworkFallbackConfig(
            enabled=_as_bool(_env_value(env, "ARTWORK_FALLBACK_ENABLED"), default=False),
            provider=(_env_value(env, "ARTWORK_FALLBACK_PROVIDER") or "musicbrainz"),
            timeout_seconds=_as_float(
                _env_value(env, "ARTWORK_FALLBACK_TIMEOUT_SEC"),
                default=DEFAULT_ARTWORK_FALLBACK_TIMEOUT,
            ),
            max_bytes=_as_int(
                _env_value(env, "ARTWORK_FALLBACK_MAX_BYTES"),
                default=DEFAULT_ARTWORK_FALLBACK_MAX_BYTES,
            ),
        ),
        post_processing=ArtworkPostProcessingConfig(
            enabled=_as_bool(
                _env_value(env, "ARTWORK_POST_PROCESSING_ENABLED"),
                default=False,
            ),
            hooks=post_processors,
        ),
    )

    ingest = IngestConfig(
        batch_size=max(
            1,
            _as_int(
                _env_value(env, "INGEST_BATCH_SIZE"),
                default=DEFAULT_INGEST_BATCH_SIZE,
            ),
        ),
        max_pending_jobs=max(
            1,
            _as_int(
                _env_value(env, "INGEST_MAX_PENDING_JOBS"),
                default=DEFAULT_INGEST_MAX_PENDING_JOBS,
            ),
        ),
    )

    free_ingest = FreeIngestConfig(
        max_playlists=max(
            1,
            _as_int(
                _env_value(env, "FREE_MAX_PLAYLISTS"),
                default=DEFAULT_FREE_INGEST_MAX_PLAYLISTS,
            ),
        ),
        max_tracks=max(
            1,
            _as_int(
                _env_value(env, "FREE_MAX_TRACKS_PER_REQUEST"),
                default=DEFAULT_FREE_INGEST_MAX_TRACKS,
            ),
        ),
        batch_size=max(
            1,
            _as_int(
                _env_value(env, "FREE_BATCH_SIZE"),
                default=DEFAULT_FREE_INGEST_BATCH_SIZE,
            ),
        ),
    )

    api_base_path = _normalise_base_path(_env_value(env, "API_BASE_PATH"))
    oauth_public_base = _normalise_prefix(
        _env_value(env, "OAUTH_PUBLIC_BASE")
        or (
            f"{api_base_path}{'/oauth' if api_base_path != '/' else 'oauth'}"
            if api_base_path
            else "/oauth"
        )
    )

    features = FeatureFlags(
        enable_artwork=_as_bool(
            _resolve_setting(
                "ENABLE_ARTWORK",
                db_settings=db_settings,
                fallback=_env_value(env, "ENABLE_ARTWORK"),
            ),
            default=False,
        ),
        enable_lyrics=_as_bool(
            _resolve_setting(
                "ENABLE_LYRICS",
                db_settings=db_settings,
                fallback=_env_value(env, "ENABLE_LYRICS"),
            ),
            default=False,
        ),
        enable_legacy_routes=_as_bool(
            _env_value(env, "FEATURE_ENABLE_LEGACY_ROUTES"),
            default=False,
        ),
        enable_artist_cache_invalidation=_as_bool(
            _env_value(env, "ARTIST_CACHE_INVALIDATE"),
            default=DEFAULT_ARTIST_CACHE_INVALIDATE,
        ),
        enable_admin_api=_as_bool(
            _env_value(env, "FEATURE_ADMIN_API"),
            default=DEFAULT_ADMIN_API_ENABLED,
        ),
    )
    ui_config = _parse_ui_config(env)

    artist_sync_config = ArtistSyncConfig(
        prune_removed=_as_bool(_env_value(env, "ARTIST_SYNC_PRUNE"), default=False),
        hard_delete=_as_bool(_env_value(env, "ARTIST_SYNC_HARD_DELETE"), default=False),
    )

    integrations = IntegrationsConfig(
        enabled=_parse_enabled_providers(_env_value(env, "INTEGRATIONS_ENABLED")),
        timeouts_ms=_parse_provider_timeouts(env),
        max_concurrency=max(
            1,
            _as_int(
                _env_value(env, "PROVIDER_MAX_CONCURRENCY"),
                default=DEFAULT_PROVIDER_MAX_CONCURRENCY,
            ),
        ),
    )

    health = HealthConfig(
        db_timeout_ms=max(
            100,
            _as_int(
                _env_value(env, "HEALTH_DB_TIMEOUT_MS"),
                default=DEFAULT_HEALTH_DB_TIMEOUT_MS,
            ),
        ),
        dependency_timeout_ms=max(
            100,
            _as_int(
                _env_value(env, "HEALTH_DEP_TIMEOUT_MS"),
                default=DEFAULT_HEALTH_DEP_TIMEOUT_MS,
            ),
        ),
        dependencies=_parse_dependency_names(_env_value(env, "HEALTH_DEPS")),
        require_database=_as_bool(_env_value(env, "HEALTH_READY_REQUIRE_DB"), default=True),
    )

    concurrency_env = _env_value(env, "WATCHLIST_MAX_CONCURRENCY")
    if concurrency_env is None:
        concurrency_env = _env_value(env, "WATCHLIST_CONCURRENCY")
    max_concurrency = min(
        10,
        max(
            1,
            _as_int(
                concurrency_env,
                default=DEFAULT_WATCHLIST_MAX_CONCURRENCY,
            ),
        ),
    )

    spotify_timeout_ms = min(
        60_000,
        max(
            100,
            _as_int(
                _env_value(env, "WATCHLIST_SPOTIFY_TIMEOUT_MS"),
                default=DEFAULT_WATCHLIST_SPOTIFY_TIMEOUT_MS,
            ),
        ),
    )

    slskd_timeout_env = _env_value(env, "WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS")
    if slskd_timeout_env is None:
        slskd_timeout_env = _env_value(env, "WATCHLIST_SEARCH_TIMEOUT_MS")
    slskd_search_timeout_ms = min(
        60_000,
        max(
            100,
            _as_int(
                slskd_timeout_env,
                default=DEFAULT_WATCHLIST_SLSKD_SEARCH_TIMEOUT_MS,
            ),
        ),
    )

    retry_env = _env_value(env, "WATCHLIST_RETRY_MAX")
    if retry_env is None:
        retry_env = _env_value(env, "WATCHLIST_BACKOFF_MAX_TRIES")
    retry_max = min(
        5,
        max(
            1,
            _as_int(
                retry_env,
                default=DEFAULT_WATCHLIST_RETRY_MAX,
            ),
        ),
    )

    retry_budget_env = _env_value(env, "ARTIST_MAX_RETRY_PER_ARTIST")
    if retry_budget_env is None:
        retry_budget_env = _env_value(env, "WATCHLIST_RETRY_BUDGET_PER_ARTIST")
    retry_budget = min(
        20,
        max(
            1,
            _as_int(
                retry_budget_env,
                default=DEFAULT_ARTIST_MAX_RETRY_PER_ARTIST,
            ),
        ),
    )

    cooldown_seconds_env = _env_value(env, "ARTIST_COOLDOWN_S")
    if cooldown_seconds_env is not None:
        cooldown_minutes = min(
            240,
            max(
                0,
                (
                    max(
                        0,
                        _as_int(
                            cooldown_seconds_env,
                            default=DEFAULT_ARTIST_COOLDOWN_SECONDS,
                        ),
                    )
                    + 59
                )
                // 60,
            ),
        )
    else:
        cooldown_minutes = min(
            240,
            max(
                0,
                _as_int(
                    _env_value(env, "WATCHLIST_COOLDOWN_MINUTES"),
                    default=DEFAULT_WATCHLIST_COOLDOWN_MINUTES,
                ),
            ),
        )

    db_io_mode_raw = (
        (_env_value(env, "WATCHLIST_DB_IO_MODE") or DEFAULT_WATCHLIST_DB_IO_MODE).strip().lower()
    )
    db_io_mode = "async" if db_io_mode_raw == "async" else "thread"

    watchlist_config = WatchlistWorkerConfig(
        max_concurrency=max_concurrency,
        max_per_tick=min(
            100,
            max(
                1,
                _as_int(
                    _env_value(env, "WATCHLIST_MAX_PER_TICK"),
                    default=DEFAULT_WATCHLIST_MAX_PER_TICK,
                ),
            ),
        ),
        spotify_timeout_ms=spotify_timeout_ms,
        slskd_search_timeout_ms=slskd_search_timeout_ms,
        tick_budget_ms=max(
            100,
            _as_int(
                _env_value(env, "WATCHLIST_TICK_BUDGET_MS"),
                default=DEFAULT_WATCHLIST_TICK_BUDGET_MS,
            ),
        ),
        backoff_base_ms=min(
            5_000,
            max(
                0,
                _as_int(
                    _env_value(env, "WATCHLIST_BACKOFF_BASE_MS"),
                    default=DEFAULT_WATCHLIST_BACKOFF_BASE_MS,
                ),
            ),
        ),
        retry_max=retry_max,
        jitter_pct=min(
            1.0,
            max(
                0.0,
                _as_float(
                    _env_value(env, "WATCHLIST_JITTER_PCT"),
                    default=DEFAULT_WATCHLIST_JITTER_PCT,
                ),
            ),
        ),
        shutdown_grace_ms=max(
            0,
            _as_int(
                _env_value(env, "WATCHLIST_SHUTDOWN_GRACE_MS"),
                default=DEFAULT_WATCHLIST_SHUTDOWN_GRACE_MS,
            ),
        ),
        db_io_mode=db_io_mode,
        retry_budget_per_artist=retry_budget,
        cooldown_minutes=cooldown_minutes,
    )

    matching_config = load_matching_config()

    admin_config = AdminConfig(
        api_enabled=features.enable_admin_api,
        staleness_max_minutes=max(
            1,
            _as_int(
                _env_value(env, "ARTIST_STALENESS_MAX_MIN"),
                default=DEFAULT_ADMIN_STALENESS_MAX_MINUTES,
            ),
        ),
        retry_budget_max=max(
            0,
            _as_int(
                _env_value(env, "ARTIST_RETRY_BUDGET_MAX"),
                default=DEFAULT_ADMIN_RETRY_BUDGET_MAX,
            ),
        ),
    )

    raw_env_keys = _parse_list(_env_value(env, "HARMONY_API_KEYS"))
    file_keys = _read_api_keys_from_file(_env_value(env, "HARMONY_API_KEYS_FILE") or "")
    api_keys = _deduplicate_preserve_order(key.strip() for key in [*raw_env_keys, *file_keys])

    default_allowlist = [
        _compose_allowlist_entry(api_base_path, suffix) for suffix in DEFAULT_ALLOWLIST_SUFFIXES
    ]
    default_allowlist.append("/api/health/ready")
    default_allowlist.append("/live")
    allowlist_override_entries = [
        _normalise_prefix(entry) for entry in _parse_list(_env_value(env, "AUTH_ALLOWLIST"))
    ]
    allowlist_entries = _deduplicate_preserve_order(
        entry for entry in [*default_allowlist, *allowlist_override_entries] if entry
    )

    request_id_config = RequestMiddlewareConfig(
        header_name=(_env_value(env, "REQUEST_ID_HEADER") or "X-Request-ID").strip()
        or "X-Request-ID"
    )

    security_profile, security_defaults = _resolve_security_profile(env)
    require_auth_override = _parse_bool_override(_env_value(env, "FEATURE_REQUIRE_AUTH"))
    rate_limit_override = _parse_bool_override(_env_value(env, "FEATURE_RATE_LIMITING"))
    rate_limit_enabled = (
        security_defaults.rate_limiting if rate_limit_override is None else rate_limit_override
    )

    rate_limit_config = RateLimitMiddlewareConfig(
        enabled=rate_limit_enabled,
        bucket_capacity=max(1, _as_int(_env_value(env, "RATE_LIMIT_BUCKET_CAP"), default=60)),
        refill_per_second=_bounded_float(
            _env_value(env, "RATE_LIMIT_REFILL_PER_SEC"),
            default=1.0,
            minimum=0.0,
        ),
    )

    cacheable_paths_env = _parse_list(_env_value(env, "CACHEABLE_PATHS"))
    merged_cacheable_paths = _deduplicate_preserve_order(
        [*cacheable_paths_env, *DEFAULT_CACHEABLE_PATH_PATTERNS]
    )
    cache_rules = _parse_cache_rules(merged_cacheable_paths)
    cache_config = CacheMiddlewareConfig(
        enabled=_as_bool(_env_value(env, "CACHE_ENABLED"), default=True),
        default_ttl=max(0, _as_int(_env_value(env, "CACHE_DEFAULT_TTL_S"), default=30)),
        max_items=max(1, _as_int(_env_value(env, "CACHE_MAX_ITEMS"), default=5_000)),
        etag_strategy=(_env_value(env, "CACHE_STRATEGY_ETAG") or "strong").strip().lower()
        or "strong",
        fail_open=_as_bool(_env_value(env, "CACHE_FAIL_OPEN"), default=True),
        stale_while_revalidate=_parse_optional_duration(
            (_env_value(env, "CACHE_STALE_WHILE_REVALIDATE_S") or "").strip() or None
        ),
        cacheable_paths=cache_rules,
        write_through=_as_bool(_env_value(env, "CACHE_WRITE_THROUGH"), default=True),
        log_evictions=_as_bool(_env_value(env, "CACHE_LOG_EVICTIONS"), default=True),
    )

    cors_origins_env = _env_value(env, "CORS_ALLOWED_ORIGINS")
    if cors_origins_env is None:
        cors_origins_env = _env_value(env, "ALLOWED_ORIGINS")
    cors_origins = _parse_list(cors_origins_env)
    if not cors_origins:
        cors_origins = ["*"]
    cors_headers = _parse_list(_env_value(env, "CORS_ALLOWED_HEADERS")) or ["*"]
    cors_methods = _parse_list(_env_value(env, "CORS_ALLOWED_METHODS")) or [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ]
    cors_config = CorsMiddlewareConfig(
        allowed_origins=_deduplicate_preserve_order(cors_origins),
        allowed_headers=_deduplicate_preserve_order(cors_headers),
        allowed_methods=_deduplicate_preserve_order(cors_methods),
    )

    gzip_config = GZipMiddlewareConfig(
        min_size=max(0, _as_int(_env_value(env, "GZIP_MIN_SIZE"), default=1_024)),
    )

    middleware_config = MiddlewareConfig(
        request_id=request_id_config,
        rate_limit=rate_limit_config,
        cache=cache_config,
        cors=cors_config,
        gzip=gzip_config,
    )

    oauth_config = OAuthConfig(
        callback_port=oauth_callback_port,
        redirect_uri=oauth_redirect_uri,
        manual_callback_enabled=oauth_manual_enabled,
        session_ttl_minutes=oauth_session_ttl_min,
        public_host_hint=oauth_public_host_hint,
        public_base=oauth_public_base,
        split_mode=oauth_split_mode,
        state_dir=oauth_state_dir,
        state_ttl_seconds=oauth_state_ttl_seconds,
        store_hash_code_verifier=oauth_store_hash_cv,
    )

    security = SecurityConfig(
        profile=security_profile,
        api_keys=api_keys,
        allowlist=allowlist_entries,
        allowed_origins=middleware_config.cors.allowed_origins,
        _require_auth_default=security_defaults.require_auth,
        _rate_limiting_default=security_defaults.rate_limiting,
        _require_auth_override=require_auth_override,
        _rate_limiting_override=rate_limit_override,
    )

    return AppConfig(
        spotify=spotify,
        oauth=oauth_config,
        soulseek=soulseek,
        logging=logging,
        database=database,
        artwork=artwork_config,
        ingest=ingest,
        free_ingest=free_ingest,
        features=features,
        ui=ui_config,
        artist_sync=artist_sync_config,
        integrations=integrations,
        security=security,
        middleware=middleware_config,
        api_base_path=api_base_path,
        health=health,
        watchlist=watchlist_config,
        matching=matching_config,
        environment=environment_config,
        admin=admin_config,
    )


def is_feature_enabled(
    name: str,
    *,
    config: AppConfig | None = None,
    database_url: str | None = None,
) -> bool:
    """Return the enabled state for the requested feature flag."""

    normalized = name.strip().lower()
    feature_key_map = {
        "artwork": "ENABLE_ARTWORK",
        "lyrics": "ENABLE_LYRICS",
    }
    try:
        key = feature_key_map[normalized]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unknown feature flag: {name}") from exc

    if config is not None:
        features = config.features
        if normalized == "artwork":
            return features.enable_artwork
        if normalized == "lyrics":
            return features.enable_lyrics

    db_value = get_setting(key, database_url=database_url)
    if db_value is not None:
        return _as_bool(db_value, default=False)

    return _as_bool(get_env(key), default=False)
