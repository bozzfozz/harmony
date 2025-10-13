"""Health and readiness checks for Harmony."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import HealthConfig
from app.logging import get_logger
from app.utils.service_health import evaluate_service_health

logger = get_logger(__name__)


@dataclass(frozen=True)
class HealthSummary:
    """Snapshot returned by the liveness endpoint."""

    status: str
    version: str
    uptime_s: float


@dataclass(frozen=True)
class DependencyStatus:
    """Represents the outcome of a single dependency probe."""

    ok: bool
    status: str


@dataclass(frozen=True)
class ReadinessResult:
    """Outcome of readiness probes for dependencies."""

    ok: bool
    database: str
    dependencies: dict[str, str]


Probe = Callable[[], bool | str | DependencyStatus | Awaitable[bool | str | DependencyStatus]]


class HealthService:
    """Execute fast health and readiness checks."""

    def __init__(
        self,
        *,
        start_time: datetime,
        version: str,
        config: HealthConfig,
        session_factory: Callable[[], Session],
        dependency_probes: Mapping[str, Probe] | None = None,
    ) -> None:
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=UTC)
        self._start_time = start_time
        self._version = version
        self._config = config
        self._session_factory = session_factory
        resolved_probes = dependency_probes or {}
        dependency_names = [name.lower() for name in config.dependencies]
        for probe_name in resolved_probes.keys():
            normalized = probe_name.lower()
            if normalized not in dependency_names:
                dependency_names.append(normalized)
        self._dependency_names = tuple(dict.fromkeys(dependency_names))
        self._dependency_probes = {name.lower(): probe for name, probe in resolved_probes.items()}

    def liveness(self) -> HealthSummary:
        """Return process information for the liveness probe."""

        now = datetime.now(UTC)
        uptime = (now - self._start_time).total_seconds()
        return HealthSummary(status="up", version=self._version, uptime_s=max(uptime, 0.0))

    async def readiness(self) -> ReadinessResult:
        """Execute readiness probes for the database and configured dependencies."""

        db_task = asyncio.create_task(self._probe_database())
        dependency_tasks: dict[str, asyncio.Task[DependencyStatus]] = {}
        for name in self._dependency_names:
            dependency_tasks[name] = asyncio.create_task(self._probe_dependency(name))

        database_status = await db_task
        dependencies: dict[str, str] = {}
        dependency_states: dict[str, DependencyStatus] = {}
        for name, task in dependency_tasks.items():
            status = await task
            dependency_states[name] = status
            dependencies[name] = status.status

        deps_ok = all(state.ok for state in dependency_states.values())
        db_ok = database_status == "up"
        ready = deps_ok and (db_ok or not self._config.require_database)
        return ReadinessResult(
            ok=ready,
            database=database_status,
            dependencies=dependencies,
        )

    async def _probe_database(self) -> str:
        timeout = max(0.1, self._config.db_timeout_ms / 1000.0)
        try:
            success = await asyncio.wait_for(
                asyncio.to_thread(self._ping_database), timeout=timeout
            )
        except TimeoutError:
            logger.warning("Database readiness probe timed out after %.2f ms", timeout * 1000)
            return "down"
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Database readiness probe failed", exc_info=exc)
            return "down"
        return "up" if success else "down"

    def _ping_database(self) -> bool:
        session = self._session_factory()
        try:
            session.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Database ping failed: %s", exc)
            return False
        finally:
            session.close()

    async def _probe_dependency(self, name: str) -> DependencyStatus:
        normalized = name.lower()
        timeout = max(0.1, self._config.dependency_timeout_ms / 1000.0)
        probe = self._dependency_probes.get(normalized)
        try:
            if probe is None:
                awaitable: Awaitable[bool | str | DependencyStatus] = asyncio.to_thread(
                    self._default_dependency_probe, normalized
                )
            else:
                result = probe()
                if isinstance(result, Awaitable):
                    awaitable = result
                else:
                    awaitable = asyncio.sleep(0, result=result)
            raw_status = await asyncio.wait_for(awaitable, timeout=timeout)
        except TimeoutError:
            logger.warning("Dependency probe timed out", extra={"dependency": name})
            return DependencyStatus(ok=False, status="down")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Dependency probe failed", exc_info=exc, extra={"dependency": name})
            return DependencyStatus(ok=False, status="down")
        normalized_status = self._normalise_dependency_status(raw_status)
        return normalized_status

    def _default_dependency_probe(self, name: str) -> bool:
        session = self._session_factory()
        try:
            health = evaluate_service_health(session, name)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to evaluate dependency %s: %s", name, exc)
            return False
        finally:
            session.close()
        return health.status == "ok"

    @staticmethod
    def _normalise_dependency_status(
        value: bool | str | DependencyStatus,
    ) -> DependencyStatus:
        if isinstance(value, DependencyStatus):
            status = value.status.strip().lower() or ("up" if value.ok else "down")
            return DependencyStatus(ok=value.ok, status=status)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if not normalized:
                return DependencyStatus(ok=False, status="down")
            if normalized in {"up", "ready", "running"}:
                return DependencyStatus(ok=True, status="up")
            if normalized in {"disabled", "skipped", "not_required"}:
                return DependencyStatus(ok=True, status=normalized)
            if normalized in {"down", "stopped", "failed", "error"}:
                return DependencyStatus(ok=False, status=normalized)
            return DependencyStatus(ok=False, status=normalized)
        status = "up" if bool(value) else "down"
        return DependencyStatus(ok=bool(value), status=status)

    @property
    def dependency_names(self) -> tuple[str, ...]:
        return self._dependency_names

    @property
    def config(self) -> HealthConfig:
        return self._config
