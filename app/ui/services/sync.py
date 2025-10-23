from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Request, status
import httpx

from app.dependencies import get_app_config
from app.errors import AppError, ErrorCode
from app.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class SyncActionResult:
    """Normalized payload describing a manual sync trigger outcome."""

    message: str
    status_code: int
    results: Mapping[str, str]
    errors: Mapping[str, str]
    counters: Mapping[str, int]


class SyncUiService:
    """HTTP-backed service to trigger manual Harmony sync operations."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def trigger_manual_sync(self, request: Request) -> SyncActionResult:
        base_url, headers = self._resolve_base_url_and_headers(request)
        sync_path = self._resolve_sync_path(request)

        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            try:
                response = await client.post(sync_path, headers=headers)
            except httpx.HTTPError as exc:
                logger.debug("dashboard.ui.sync_request_failed", exc_info=True)
                raise AppError(
                    "Unable to trigger a manual sync run.",
                    code=ErrorCode.DEPENDENCY_ERROR,
                ) from exc

        payload = self._decode_payload(response)
        if response.status_code >= status.HTTP_400_BAD_REQUEST:
            message = self._extract_error_message(payload)
            meta = self._extract_error_meta(payload)
            raise AppError(
                message,
                code=ErrorCode.DEPENDENCY_ERROR,
                http_status=response.status_code,
                meta=meta,
            )

        result = self._build_result(response.status_code, payload)
        logger.debug(
            "dashboard.ui.sync_request_succeeded",
            extra={
                "results": len(result.results),
                "errors": len(result.errors),
                "status_code": result.status_code,
            },
        )
        return result

    def _resolve_sync_path(self, request: Request) -> str:
        base_path = self._resolve_api_base_path(request)
        if base_path:
            normalized = base_path.rstrip("/")
            if normalized:
                return f"{normalized}/sync"
        return "/api/v1/sync"

    def _resolve_api_base_path(self, request: Request) -> str:
        base_path = getattr(request.app.state, "api_base_path", None)
        if isinstance(base_path, str) and base_path:
            return base_path
        config = get_app_config()
        return config.api_base_path or ""

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
    def _decode_payload(response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                "Harmony API returned an unexpected response.",
                code=ErrorCode.DEPENDENCY_ERROR,
                http_status=response.status_code,
            ) from exc
        if not isinstance(payload, Mapping):
            raise AppError(
                "Harmony API returned an unexpected payload shape.",
                code=ErrorCode.DEPENDENCY_ERROR,
                http_status=response.status_code,
            )
        return payload

    @staticmethod
    def _extract_error_message(payload: Mapping[str, Any]) -> str:
        detail = payload.get("detail")
        if isinstance(detail, Mapping):
            message = detail.get("message")
            if isinstance(message, str) and message.strip():
                return message
        message_raw = payload.get("message")
        if isinstance(message_raw, str) and message_raw.strip():
            return message_raw
        return "Failed to trigger manual sync."

    @staticmethod
    def _extract_error_meta(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
        detail = payload.get("detail")
        candidates: Sequence[tuple[str, Any]]
        if isinstance(detail, Mapping):
            candidates = detail.items()
        else:
            candidates = ()
        meta: dict[str, Any] = {}
        for key, value in candidates:
            if key == "message":
                continue
            meta[key] = value
        if not meta:
            return None
        return meta

    @staticmethod
    def _build_result(status_code: int, payload: Mapping[str, Any]) -> SyncActionResult:
        message = str(payload.get("message") or "Sync triggered")
        results_raw = payload.get("results")
        results: dict[str, str] = {}
        if isinstance(results_raw, Mapping):
            for name, status_text in results_raw.items():
                results[str(name)] = str(status_text or "")
        errors_raw = payload.get("errors")
        errors: dict[str, str] = {}
        if isinstance(errors_raw, Mapping):
            for name, error_text in errors_raw.items():
                errors[str(name)] = str(error_text or "")
        counters_raw = payload.get("counters")
        counters: dict[str, int] = {}
        if isinstance(counters_raw, Mapping):
            for key, value in counters_raw.items():
                if isinstance(value, (int, float)):
                    counters[str(key)] = int(value)
        return SyncActionResult(
            message=message,
            status_code=status_code,
            results=results,
            errors=errors,
            counters=counters,
        )


def get_sync_ui_service() -> SyncUiService:
    """FastAPI dependency returning the sync UI service instance."""

    return SyncUiService()


__all__ = ["SyncActionResult", "SyncUiService", "get_sync_ui_service"]
