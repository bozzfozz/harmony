from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Literal

from fastapi import HTTPException, Request, Response, status

from app.config import SecurityConfig, get_env
from app.dependencies import get_app_config
from app.logging import get_logger
from app.logging_events import log_event
from app.utils.metrics import counter

from .session_store import StoredUiSession, UiSessionStore

RoleName = Literal["read_only", "operator", "admin"]

_ROLE_ORDER: dict[RoleName, int] = {
    "read_only": 0,
    "operator": 1,
    "admin": 2,
}

_SESSION_COOKIE = "ui_session"

logger = get_logger(__name__)

_SESSION_CREATED_METRIC_NAME = "ui_sessions_created_total"
_SESSION_CREATED_METRIC_DOC = "Total number of Harmony UI sessions successfully created"
_SESSION_TERMINATED_METRIC_NAME = "ui_sessions_terminated_total"
_SESSION_TERMINATED_METRIC_DOC = "Total number of Harmony UI sessions terminated grouped by reason"


def register_ui_session_metrics() -> None:
    """Register Prometheus metrics tracking UI session lifecycle events."""

    counter(
        _SESSION_CREATED_METRIC_NAME,
        _SESSION_CREATED_METRIC_DOC,
        label_names=("role",),
    )
    counter(
        _SESSION_TERMINATED_METRIC_NAME,
        _SESSION_TERMINATED_METRIC_DOC,
        label_names=("role", "reason"),
    )


def _session_created_counter():
    return counter(
        _SESSION_CREATED_METRIC_NAME,
        _SESSION_CREATED_METRIC_DOC,
        label_names=("role",),
    )


def _session_terminated_counter():
    return counter(
        _SESSION_TERMINATED_METRIC_NAME,
        _SESSION_TERMINATED_METRIC_DOC,
        label_names=("role", "reason"),
    )


def _record_session_created(role: RoleName) -> None:
    _session_created_counter().labels(role=role).inc()


def _record_session_termination(session: UiSession, *, reason: str) -> None:
    if reason == "logout":
        component = "ui.router"
        status = "success"
    else:
        component = "ui.session"
        status = reason

    log_event(
        logger,
        "ui.session.ended",
        component=component,
        status=status,
        role=session.role,
        reason=reason,
    )
    _session_terminated_counter().labels(role=session.role, reason=reason).inc()


@dataclass(slots=True, frozen=True)
class UiFeatures:
    spotify: bool
    soulseek: bool
    dlq: bool
    imports: bool


@dataclass(slots=True)
class UiJobState:
    spotify_free_ingest_job_id: str | None = None
    spotify_backfill_job_id: str | None = None


@dataclass(slots=True)
class UiSession:
    identifier: str
    role: RoleName
    features: UiFeatures
    fingerprint: str
    issued_at: datetime
    last_seen_at: datetime
    jobs: UiJobState = field(default_factory=UiJobState)

    def allows(self, required: RoleName) -> bool:
        return _ROLE_ORDER[self.role] >= _ROLE_ORDER[required]


class UiSessionManager:
    """Durable UI session registry with API-key validation."""

    def __init__(
        self,
        security: SecurityConfig,
        *,
        role_default: RoleName,
        role_overrides: dict[str, RoleName],
        session_ttl: timedelta,
        features: UiFeatures,
        store: UiSessionStore | None = None,
    ) -> None:
        self._security = security
        self._role_default = role_default
        self._role_overrides = role_overrides
        self._session_ttl = session_ttl
        self._features = features
        self._store = store or UiSessionStore()
        self._lock = asyncio.Lock()

    async def create_session(self, api_key: str) -> UiSession:
        normalized = api_key.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An API key is required.",
            )

        if not self._security.api_keys:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="UI login is not available without configured API keys.",
            )

        if not self._is_valid_key(normalized):
            fingerprint = fingerprint_api_key(normalized)
            log_event(
                logger,
                "ui.login",  # pragma: no cover - logging
                component="ui.session",
                status="denied",
                fingerprint=fingerprint,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The provided API key is not valid.",
            )

        fingerprint = fingerprint_api_key(normalized)
        role = self._resolve_role(fingerprint)
        identifier = secrets.token_urlsafe(32)
        issued_at = datetime.now(tz=UTC)
        session = UiSession(
            identifier=identifier,
            role=role,
            features=self._features,
            fingerprint=fingerprint,
            issued_at=issued_at,
            last_seen_at=issued_at,
        )
        async with self._lock:
            self._store.create_session(self._stored_from_session(session))
        log_event(
            logger,
            "ui.login",
            component="ui.session",
            status="granted",
            fingerprint=fingerprint,
            role=role,
        )
        _record_session_created(role)
        return session

    async def get_session(self, identifier: str) -> UiSession | None:
        async with self._lock:
            return self._get_active_session(identifier)

    async def invalidate(self, identifier: str, *, reason: str = "logout") -> None:
        async with self._lock:
            stored = self._store.delete_session(identifier)
        if stored is not None:
            _record_session_termination(self._session_from_stored(stored), reason=reason)

    def cookie_max_age(self) -> int:
        return int(self._session_ttl.total_seconds())

    async def get_spotify_free_ingest_job_id(self, identifier: str) -> str | None:
        async with self._lock:
            session = self._get_active_session(identifier)
            if session is None:
                return None
            return session.jobs.spotify_free_ingest_job_id

    async def set_spotify_free_ingest_job_id(self, identifier: str, job_id: str | None) -> None:
        async with self._lock:
            session = self._get_active_session(identifier)
            if session is None:
                return
            self._store.set_spotify_free_ingest_job_id(identifier, job_id)

    async def get_spotify_backfill_job_id(self, identifier: str) -> str | None:
        async with self._lock:
            session = self._get_active_session(identifier)
            if session is None:
                return None
            return session.jobs.spotify_backfill_job_id

    async def set_spotify_backfill_job_id(self, identifier: str, job_id: str | None) -> None:
        async with self._lock:
            session = self._get_active_session(identifier)
            if session is None:
                return
            self._store.set_spotify_backfill_job_id(identifier, job_id)

    async def clear_job_state(self, identifier: str) -> None:
        async with self._lock:
            session = self._get_active_session(identifier)
            if session is None:
                return
            self._store.clear_job_state(identifier)

    def _stored_from_session(self, session: UiSession) -> StoredUiSession:
        return StoredUiSession(
            identifier=session.identifier,
            role=session.role,
            fingerprint=session.fingerprint,
            issued_at=session.issued_at,
            last_seen_at=session.last_seen_at,
            feature_spotify=session.features.spotify,
            feature_soulseek=session.features.soulseek,
            feature_dlq=session.features.dlq,
            feature_imports=session.features.imports,
            spotify_free_ingest_job_id=session.jobs.spotify_free_ingest_job_id,
            spotify_backfill_job_id=session.jobs.spotify_backfill_job_id,
        )

    def _session_from_stored(self, stored: StoredUiSession) -> UiSession:
        session = UiSession(
            identifier=stored.identifier,
            role=stored.role,  # type: ignore[arg-type]
            features=UiFeatures(
                spotify=stored.feature_spotify,
                soulseek=stored.feature_soulseek,
                dlq=stored.feature_dlq,
                imports=stored.feature_imports,
            ),
            fingerprint=stored.fingerprint,
            issued_at=stored.issued_at,
            last_seen_at=stored.last_seen_at,
        )
        session.jobs.spotify_free_ingest_job_id = stored.spotify_free_ingest_job_id
        session.jobs.spotify_backfill_job_id = stored.spotify_backfill_job_id
        return session

    def _is_valid_key(self, candidate: str) -> bool:
        return any(
            hmac.compare_digest(candidate, configured) for configured in self._security.api_keys
        )

    def _resolve_role(self, fingerprint: str) -> RoleName:
        try:
            override = self._role_overrides[fingerprint]
        except KeyError:
            override = None
        return override or self._role_default

    def _is_expired(self, session: UiSession) -> bool:
        return session.last_seen_at + self._session_ttl < datetime.now(tz=UTC)

    def _get_active_session(self, identifier: str) -> UiSession | None:
        stored = self._store.get_session(identifier)
        if stored is None:
            return None
        session = self._session_from_stored(stored)
        if self._is_expired(session):
            removed = self._store.delete_session(identifier)
            if removed is not None:
                _record_session_termination(self._session_from_stored(removed), reason="expired")
            return None
        now = datetime.now(tz=UTC)
        self._store.update_last_seen(identifier, now)
        session.last_seen_at = now
        return session

    @property
    def security(self) -> SecurityConfig:
        return self._security


def fingerprint_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _parse_role(value: str | None, *, fallback: RoleName) -> RoleName:
    if not value:
        return fallback
    normalized = value.strip().lower()
    if normalized in _ROLE_ORDER:
        return normalized  # type: ignore[return-value]
    return fallback


def _load_role_overrides(default: RoleName) -> dict[str, RoleName]:
    raw = get_env("UI_ROLE_OVERRIDES") or ""
    overrides: dict[str, RoleName] = {}
    for entry in (segment.strip() for segment in raw.split(",")):
        if not entry:
            continue
        key, _, value = entry.partition(":")
        key = key.strip()
        if not key:
            continue
        overrides[key] = _parse_role(value, fallback=default)
    return overrides


def _load_features() -> UiFeatures:
    return UiFeatures(
        spotify=_as_bool(get_env("UI_FEATURE_SPOTIFY"), default=True),
        soulseek=_as_bool(get_env("UI_FEATURE_SOULSEEK"), default=True),
        dlq=_as_bool(get_env("UI_FEATURE_DLQ"), default=True),
        imports=_as_bool(get_env("UI_FEATURE_IMPORTS"), default=True),
    )


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_session_ttl() -> timedelta:
    raw = get_env("UI_SESSION_TTL_MINUTES")
    minutes = 480
    if raw:
        try:
            value = int(raw.strip())
        except ValueError:
            value = minutes
        else:
            if value > 0:
                minutes = value
    return timedelta(minutes=minutes)


def build_session_manager(config: SecurityConfig | None = None) -> UiSessionManager:
    security = config or get_app_config().security
    role_default = _parse_role(get_env("UI_ROLE_DEFAULT"), fallback="operator")
    overrides = _load_role_overrides(role_default)
    features = _load_features()
    ttl = _resolve_session_ttl()
    return UiSessionManager(
        security,
        role_default=role_default,
        role_overrides=overrides,
        session_ttl=ttl,
        features=features,
    )


def get_session_manager(request: Request) -> UiSessionManager:
    manager: UiSessionManager | None = getattr(request.app.state, "ui_session_manager", None)
    if manager is None:
        config_snapshot = getattr(request.app.state, "config_snapshot", None)
        security = config_snapshot.security if config_snapshot else get_app_config().security
        manager = build_session_manager(security)
        request.app.state.ui_session_manager = manager
    return manager


async def get_spotify_free_ingest_job_id(request: Request, session: UiSession) -> str | None:
    manager = get_session_manager(request)
    return await manager.get_spotify_free_ingest_job_id(session.identifier)


async def set_spotify_free_ingest_job_id(
    request: Request, session: UiSession, job_id: str | None
) -> None:
    manager = get_session_manager(request)
    await manager.set_spotify_free_ingest_job_id(session.identifier, job_id)


async def get_spotify_backfill_job_id(request: Request, session: UiSession) -> str | None:
    manager = get_session_manager(request)
    return await manager.get_spotify_backfill_job_id(session.identifier)


async def set_spotify_backfill_job_id(
    request: Request, session: UiSession, job_id: str | None
) -> None:
    manager = get_session_manager(request)
    await manager.set_spotify_backfill_job_id(session.identifier, job_id)


async def clear_spotify_job_state(request: Request, session: UiSession) -> None:
    manager = get_session_manager(request)
    await manager.clear_job_state(session.identifier)


async def require_session(request: Request) -> UiSession:
    manager = get_session_manager(request)
    session_id = request.cookies.get(_SESSION_COOKIE)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid UI session is required.",
        )
    session = await manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The UI session has expired.",
        )
    return session


def require_role(required: RoleName):
    async def dependency(request: Request) -> UiSession:
        session = await require_session(request)
        if not session.allows(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The current UI session lacks permission for this action.",
            )
        return session

    return dependency


def require_feature(feature: Literal["spotify", "soulseek", "dlq", "imports"]):
    async def dependency(request: Request) -> UiSession:
        session = await require_session(request)
        if not getattr(session.features, feature, False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The requested UI feature is disabled.",
            )
        return session

    return dependency


def require_admin_with_feature(
    feature: Literal["spotify", "soulseek", "dlq", "imports"],
) -> Callable[[Request], Awaitable[UiSession]]:
    admin_dependency = require_role("admin")

    async def dependency(request: Request) -> UiSession:
        session = await admin_dependency(request)
        if not getattr(session.features, feature, False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The requested UI feature is disabled.",
            )
        return session

    return dependency


def require_operator_with_feature(
    feature: Literal["spotify", "soulseek", "dlq", "imports"],
) -> Callable[[Request], Awaitable[UiSession]]:
    operator_dependency = require_role("operator")

    async def dependency(request: Request) -> UiSession:
        session = await operator_dependency(request)
        if not getattr(session.features, feature, False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The requested UI feature is disabled.",
            )
        return session

    return dependency


def attach_session_cookie(
    response: Response, session: UiSession, manager: UiSessionManager
) -> None:
    secure = manager.security.ui_cookies_secure
    response.set_cookie(
        _SESSION_COOKIE,
        session.identifier,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=manager.cookie_max_age(),
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        _SESSION_COOKIE,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


__all__ = [
    "RoleName",
    "UiFeatures",
    "UiJobState",
    "UiSession",
    "UiSessionManager",
    "attach_session_cookie",
    "clear_spotify_job_state",
    "build_session_manager",
    "clear_session_cookie",
    "fingerprint_api_key",
    "get_spotify_backfill_job_id",
    "get_spotify_free_ingest_job_id",
    "get_session_manager",
    "require_admin_with_feature",
    "require_role",
    "require_feature",
    "require_operator_with_feature",
    "require_session",
    "register_ui_session_metrics",
    "set_spotify_backfill_job_id",
    "set_spotify_free_ingest_job_id",
]
