"""Health and readiness checks for Harmony."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

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
class ReadinessResult:
    """Outcome of readiness probes for dependencies."""

    ok: bool
    database: str
    dependencies: dict[str, str]


Probe = Callable[[], bool | Awaitable[bool]]


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
            start_time = start_time.replace(tzinfo=timezone.utc)
        self._start_time = start_time
        self._version = version
        self._config = config
        self._session_factory = session_factory
        self._dependency_names = tuple(config.dependencies)
        self._dependency_probes = {
            name.lower(): probe for name, probe in (dependency_probes or {}).items()
        }

    def liveness(self) -> HealthSummary:
        """Return process information for the liveness probe."""

        now = datetime.now(timezone.utc)
        uptime = (now - self._start_time).total_seconds()
        return HealthSummary(status="up", version=self._version, uptime_s=max(uptime, 0.0))

    async def readiness(self) -> ReadinessResult:
        """Execute readiness probes for the database and configured dependencies."""

        db_task = asyncio.create_task(self._probe_database())
        dependency_tasks: dict[str, asyncio.Task[str]] = {}
        for name in self._dependency_names:
            dependency_tasks[name] = asyncio.create_task(self._probe_dependency(name))

        database_status = await db_task
        dependencies: dict[str, str] = {}
        for name, task in dependency_tasks.items():
            dependencies[name] = await task

        deps_ok = all(status == "up" for status in dependencies.values())
        db_ok = database_status == "up"
        ready = deps_ok and (db_ok or not self._config.require_database)
        return ReadinessResult(ok=ready, database=database_status, dependencies=dependencies)

    async def _probe_database(self) -> str:
        timeout = max(0.1, self._config.db_timeout_ms / 1000.0)
        try:
            success = await asyncio.wait_for(
                asyncio.to_thread(self._ping_database), timeout=timeout
            )
        except asyncio.TimeoutError:
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

    async def _probe_dependency(self, name: str) -> str:
        normalized = name.lower()
        timeout = max(0.1, self._config.dependency_timeout_ms / 1000.0)
        probe = self._dependency_probes.get(normalized)
        try:
            if probe is None:
                awaitable: Awaitable[bool] = asyncio.to_thread(
                    self._default_dependency_probe, normalized
                )
            else:
                result = probe()
                if isinstance(result, Awaitable):
                    awaitable = result
                else:
                    awaitable = asyncio.sleep(0, result=bool(result))
            success = await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Dependency probe timed out", extra={"dependency": name})
            return "down"
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Dependency probe failed", exc_info=exc, extra={"dependency": name})
            return "down"
        return "up" if success else "down"

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

    @property
    def dependency_names(self) -> tuple[str, ...]:
        return self._dependency_names

    @property
    def config(self) -> HealthConfig:
        return self._config
