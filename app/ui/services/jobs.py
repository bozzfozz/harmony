from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fastapi import Request, status

from app.api.system import get_readiness
from app.errors import AppError, ErrorCode
from app.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class OrchestratorJob:
    name: str
    status: str
    enabled: bool


class JobsUiService:
    """Expose orchestrator readiness state to UI fragments."""

    async def list_jobs(self, request: Request) -> Sequence[OrchestratorJob]:
        payload = await get_readiness(request)
        if not payload.get("ok", False):
            error = payload.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else None
            logger.error(
                "jobs.ui.readiness_failed",
                extra={"error": error},
            )
            raise AppError(
                message or "Failed to load orchestrator jobs.",
                code=ErrorCode.DEPENDENCY_ERROR,
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        data = payload.get("data", {})
        orchestrator = data.get("orchestrator", {}) if isinstance(data, dict) else {}
        jobs = orchestrator.get("jobs", {}) if isinstance(orchestrator, dict) else {}
        enabled_jobs = orchestrator.get("enabled_jobs", {}) if isinstance(orchestrator, dict) else {}

        rows: list[OrchestratorJob] = []
        for name, status_text in sorted(jobs.items()):
            enabled = bool(enabled_jobs.get(name, True))
            rows.append(
                OrchestratorJob(
                    name=str(name),
                    status=str(status_text or "unknown"),
                    enabled=enabled,
                )
            )

        logger.debug("jobs.ui.list", extra={"count": len(rows)})
        return tuple(rows)


__all__ = ["JobsUiService", "OrchestratorJob"]
