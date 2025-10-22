"""Dashboard UI service fetching backend health and status summaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request, status

from app.dependencies import get_app_config
from app.errors import AppError, ErrorCode
from app.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class DashboardConnectionStatus:
    name: str
    status: str


@dataclass(slots=True)
class DashboardHealthIssue:
    component: str
    message: str
    exit_code: int | None = None
    details: Mapping[str, Any] | None = None


@dataclass(slots=True)
class DashboardStatusSummary:
    status: str
    version: str | None
    uptime_seconds: float | None
    readiness_status: str | None
    connections: Sequence[DashboardConnectionStatus]
    readiness_issues: Sequence[DashboardHealthIssue]


@dataclass(slots=True)
class DashboardHealthSummary:
    live_status: str
    ready_status: str
    ready_ok: bool
    checks: Mapping[str, Any]
    issues: Sequence[DashboardHealthIssue]


@dataclass(slots=True)
class DashboardWorkerStatus:
    name: str
    status: str
    queue_size: int | None
    last_seen: str | None
    component: str | None
    job: str | None


class DashboardUiService:
    """HTTP-backed service exposing dashboard status fragments."""

    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = timeout

    async def fetch_status(self, request: Request) -> DashboardStatusSummary:
        payload = await self._fetch_status_payload(request)
        connections_raw = payload.get("connections")
        connections: list[DashboardConnectionStatus] = []
        if isinstance(connections_raw, Mapping):
            for name, status_text in sorted(connections_raw.items()):
                connections.append(
                    DashboardConnectionStatus(
                        name=str(name),
                        status=str(status_text or "unknown"),
                    )
                )

        readiness_raw = payload.get("readiness")
        readiness_status: str | None = None
        readiness_issues: list[DashboardHealthIssue] = []
        if isinstance(readiness_raw, Mapping):
            readiness_status = str(readiness_raw.get("status", "unknown"))
            issues_raw = readiness_raw.get("issues")
            if isinstance(issues_raw, Sequence):
                for issue in issues_raw:
                    if isinstance(issue, Mapping):
                        readiness_issues.append(self._parse_issue(issue))

        uptime_raw = payload.get("uptime_seconds")
        uptime_seconds: float | None
        if isinstance(uptime_raw, (int, float)):
            uptime_seconds = float(uptime_raw)
        else:
            uptime_seconds = None

        version = payload.get("version")
        if version is not None:
            version = str(version)

        status_text = str(payload.get("status", "unknown"))
        logger.debug(
            "dashboard.ui.status_payload",
            extra={
                "connections": len(connections),
                "readiness_issues": len(readiness_issues),
                "status": status_text,
            },
        )
        return DashboardStatusSummary(
            status=status_text,
            version=version,
            uptime_seconds=uptime_seconds,
            readiness_status=readiness_status,
            connections=tuple(connections),
            readiness_issues=tuple(readiness_issues),
        )

    async def fetch_health(self, request: Request) -> DashboardHealthSummary:
        base_url, headers = self._resolve_base_url_and_headers(request)
        live_path = "/api/health/live"
        ready_path = "/api/health/ready"

        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            try:
                live_response, ready_response = await asyncio.gather(
                    client.get(live_path, headers=headers),
                    client.get(ready_path, headers=headers),
                )
            except httpx.HTTPError as exc:
                logger.debug("dashboard.ui.health_request_failed", exc_info=True)
                raise AppError(
                    "Unable to load health information.",
                    code=ErrorCode.DEPENDENCY_ERROR,
                ) from exc

        live_payload = self._decode_json(live_response, expect_ok=True, path=live_path)
        ready_payload = self._decode_json(ready_response, expect_ok=False, path=ready_path)

        live_status = str(live_payload.get("status", "unknown"))
        ready_status = str(ready_payload.get("status", "unknown"))
        ready_ok = ready_response.status_code == status.HTTP_200_OK
        checks_raw = ready_payload.get("checks")
        checks = checks_raw if isinstance(checks_raw, Mapping) else {}
        issues_raw = ready_payload.get("issues")
        issues: list[DashboardHealthIssue] = []
        if isinstance(issues_raw, Sequence):
            for issue in issues_raw:
                if isinstance(issue, Mapping):
                    issues.append(self._parse_issue(issue))

        logger.debug(
            "dashboard.ui.health_payload",
            extra={
                "live_status": live_status,
                "ready_status": ready_status,
                "issues": len(issues),
            },
        )
        return DashboardHealthSummary(
            live_status=live_status,
            ready_status=ready_status,
            ready_ok=ready_ok,
            checks=checks if isinstance(checks, Mapping) else {},
            issues=tuple(issues),
        )

    async def fetch_workers(self, request: Request) -> Sequence[DashboardWorkerStatus]:
        payload = await self._fetch_status_payload(request)
        workers_raw = payload.get("workers")
        if not isinstance(workers_raw, Mapping):
            return ()

        workers: list[DashboardWorkerStatus] = []
        for name, details_raw in sorted(workers_raw.items()):
            if not isinstance(details_raw, Mapping):
                continue
            status_text = str(details_raw.get("status", "unknown"))
            queue_raw = details_raw.get("queue_size")
            queue_size: int | None
            if isinstance(queue_raw, (int, float)):
                queue_size = int(queue_raw)
            else:
                queue_size = None
            last_seen_raw = details_raw.get("last_seen")
            last_seen = str(last_seen_raw) if last_seen_raw is not None else None
            component = (
                str(details_raw.get("component"))
                if details_raw.get("component") is not None
                else None
            )
            job = str(details_raw.get("job")) if details_raw.get("job") is not None else None
            workers.append(
                DashboardWorkerStatus(
                    name=str(name),
                    status=status_text,
                    queue_size=queue_size,
                    last_seen=last_seen,
                    component=component,
                    job=job,
                )
            )

        logger.debug(
            "dashboard.ui.workers_payload",
            extra={"count": len(workers)},
        )
        return tuple(workers)

    async def _fetch_status_payload(self, request: Request) -> Mapping[str, Any]:
        base_url, headers = self._resolve_base_url_and_headers(request)
        api_base_path = self._resolve_api_base_path(request)
        status_path = f"{api_base_path}/status" if api_base_path else "/status"
        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            try:
                response = await client.get(status_path, headers=headers)
            except httpx.HTTPError as exc:
                logger.debug("dashboard.ui.status_request_failed", exc_info=True)
                raise AppError(
                    "Unable to load dashboard status.",
                    code=ErrorCode.DEPENDENCY_ERROR,
                ) from exc
        payload = self._decode_json(response, expect_ok=True, path=status_path)
        if not isinstance(payload, Mapping):
            raise AppError(
                "Dashboard status payload is not valid.",
                code=ErrorCode.DEPENDENCY_ERROR,
            )
        return payload

    def _resolve_api_base_path(self, request: Request) -> str:
        base_path = getattr(request.app.state, "api_base_path", None)
        if isinstance(base_path, str) and base_path:
            normalized = base_path.rstrip("/")
            return normalized if normalized else ""
        config = get_app_config()
        candidate = config.api_base_path.rstrip("/")
        return candidate if candidate else ""

    def _resolve_base_url_and_headers(self, request: Request) -> tuple[str, Mapping[str, str]]:
        base_url = str(request.base_url)
        headers: dict[str, str] = {"Accept": "application/json"}
        security = getattr(request.app.state, "security_config", None)
        if security is not None and security.resolve_require_auth():
            if not security.api_keys:
                raise AppError(
                    "API key authentication is enabled but no keys are configured.",
                    code=ErrorCode.INTERNAL_ERROR,
                )
            headers["X-API-Key"] = security.api_keys[0]
        return base_url, headers

    @staticmethod
    def _decode_json(
        response: httpx.Response,
        *,
        expect_ok: bool,
        path: str,
    ) -> Mapping[str, Any]:
        if expect_ok and response.status_code >= 400:
            raise AppError(
                "Received an unexpected response from the Harmony API.",
                code=ErrorCode.DEPENDENCY_ERROR,
                http_status=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                "Harmony API returned invalid JSON.",
                code=ErrorCode.DEPENDENCY_ERROR,
            ) from exc
        if not isinstance(payload, Mapping):
            raise AppError(
                "Harmony API returned an unexpected payload shape.",
                code=ErrorCode.DEPENDENCY_ERROR,
            )
        return payload

    @staticmethod
    def _parse_issue(issue: Mapping[str, Any]) -> DashboardHealthIssue:
        component = str(issue.get("component", "unknown"))
        message = str(issue.get("message", "")) or "Unknown issue"
        exit_code_raw = issue.get("exit_code")
        exit_code = int(exit_code_raw) if isinstance(exit_code_raw, int) else None
        details_raw = issue.get("details")
        details = details_raw if isinstance(details_raw, Mapping) else None
        return DashboardHealthIssue(
            component=component,
            message=message,
            exit_code=exit_code,
            details=details,
        )


def get_dashboard_ui_service() -> DashboardUiService:
    """FastAPI dependency returning the dashboard UI service instance."""

    return DashboardUiService()


__all__ = [
    "DashboardConnectionStatus",
    "DashboardHealthIssue",
    "DashboardHealthSummary",
    "DashboardStatusSummary",
    "DashboardUiService",
    "DashboardWorkerStatus",
    "get_dashboard_ui_service",
]
