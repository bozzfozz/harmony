"""Global exception handling for the public API."""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import (AppError, ErrorCode, InternalServerError,
                        rate_limit_meta, to_response)
from app.logging import get_logger

try:  # pragma: no cover - Python <3.11 fallback
    ExceptionGroup  # type: ignore[used-before-assignment]
except NameError:  # pragma: no cover - compatibility branch

    class ExceptionGroup(Exception):  # type: ignore[override]
        """Compatibility shim for environments without ``ExceptionGroup``."""


_logger = get_logger(__name__)


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


async def _handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        request_path=request.url.path,
        method=request.method,
        meta=meta,
    )


async def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return await _render_http_exception(
        request,
        status_code=exc.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=exc.detail,
        headers=exc.headers,
    )


async def _handle_starlette_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return await _render_http_exception(
        request,
        status_code=exc.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=exc.detail,
        headers=exc.headers,
    )


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return exc.as_response(request_path=request.url.path, method=request.method)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    _logger.exception("Unhandled application error", exc_info=exc)
    error = InternalServerError()
    return error.as_response(request_path=request.url.path, method=request.method)


async def _handle_exception_group(request: Request, exc: ExceptionGroup) -> JSONResponse:  # type: ignore[override]
    _logger.exception("Unhandled application error group", exc_info=exc)
    error = InternalServerError()
    return error.as_response(request_path=request.url.path, method=request.method)


def setup_exception_handlers(app: FastAPI) -> None:
    """Register the canonical exception handlers for the API."""

    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(HTTPException, _handle_http_exception)
    app.add_exception_handler(StarletteHTTPException, _handle_starlette_http_exception)
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
    # ``ExceptionGroup`` exists in Python >=3.11.
    if ExceptionGroup is not Exception:  # pragma: no branch - type guard
        app.add_exception_handler(ExceptionGroup, _handle_exception_group)  # type: ignore[arg-type]


__all__ = ["setup_exception_handlers"]
