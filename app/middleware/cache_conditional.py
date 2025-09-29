"""Middleware for HTTP conditional requests and response caching."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import Awaitable, Callable, Mapping

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.services.cache import (
    CacheEntry,
    ResponseCache,
    build_cache_key,
    resolve_auth_variant,
)
from app.errors import AppError, InternalServerError

if sys.version_info < (3, 11):  # pragma: no cover - Python <3.11 fallback

    class ExceptionGroup(Exception):  # type: ignore[override]
        """Compatibility stub for Python versions without ExceptionGroup."""


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CachePolicy:
    """Caching policy for a single route."""

    path: str
    max_age: int
    stale_while_revalidate: int

    @property
    def cache_control(self) -> str:
        stale_value = max(self.stale_while_revalidate, 0)
        parts = ["public", f"max-age={max(self.max_age, 0)}"]
        if stale_value:
            parts.append(f"stale-while-revalidate={stale_value}")
        return ", ".join(parts)


class ConditionalCacheMiddleware(BaseHTTPMiddleware):
    """Apply ETag/Last-Modified headers and serve 304 responses when possible."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        cache: ResponseCache,
        enabled: bool,
        policies: Mapping[str, CachePolicy],
        default_policy: CachePolicy,
        etag_strategy: str = "strong",
        vary_headers: tuple[str, ...] = ("Authorization", "X-API-Key", "Origin", "Accept-Encoding"),
    ) -> None:
        super().__init__(app)
        self._cache = cache
        self._enabled = enabled
        self._policies = policies
        self._default_policy = default_policy
        self._etag_strategy = etag_strategy.lower()
        self._vary_headers = vary_headers

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self._enabled:
            return await self._call_next(request, call_next)

        method = request.method.upper()
        cache_method = "GET" if method == "HEAD" else method
        route = request.scope.get("route")
        path_template = getattr(route, "path_format", request.url.path)

        if cache_method != "GET":
            response = await self._call_next(request, call_next)
            if cache_method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
                await self._invalidate_related(path_template)
            return response

        if not self._is_cacheable_path(path_template):
            response = await self._call_next(request, call_next)
            return self._apply_headers(response, path_template, method=method)

        cache_key = self._build_cache_key(request, path_template, cache_method)
        entry = await self._safe_cache_get(cache_key)
        if entry is not None:
            if self._is_not_modified(request, entry):
                return self._build_not_modified_response(entry)
            return self._build_cached_response(entry, method=method)

        response = await self._call_next(request, call_next)
        return await self._store_and_respond(
            request,
            response,
            path_template,
            cache_key,
            method=method,
        )

    async def _call_next(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except ExceptionGroup as exc:  # pragma: no cover - defensive
            if len(exc.exceptions) == 1:
                raise exc.exceptions[0]
            raise
        except (HTTPException, AppError):
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unhandled error in cache middleware", exc_info=exc)
            error = InternalServerError()
            return error.as_response(request_path=request.url.path, method=request.method)

    def _is_cacheable_path(self, path_template: str) -> bool:
        return path_template in self._policies

    def _policy_for(self, path_template: str) -> CachePolicy:
        return self._policies.get(path_template, self._default_policy)

    async def _safe_cache_get(self, cache_key: str) -> CacheEntry | None:
        try:
            return await self._cache.get(cache_key)
        except Exception:  # pragma: no cover - defensive
            if not self._cache.fail_open:
                raise
            logger.warning(
                "Cache get failed; serving origin response",
                extra={"event": "cache.error", "key": cache_key},
            )
            return None

    async def _store_and_respond(
        self,
        request: Request,
        response: Response,
        path_template: str,
        cache_key: str,
        *,
        method: str,
    ) -> Response:
        policy = self._policy_for(path_template)
        if method.upper() != "GET":
            enriched = None
        else:
            enriched = await self._prepare_response(response, policy, path_template)
        if enriched is None:
            applied = self._apply_headers(response, path_template, method=method)
            return self._ensure_head_semantics(applied, method)

        try:
            enriched.key = cache_key
            await self._cache.set(cache_key, enriched, ttl=policy.max_age)
        except Exception:  # pragma: no cover - defensive
            if not self._cache.fail_open:
                raise
            logger.warning(
                "Cache store failed; continuing without cache",
                extra={"event": "cache.error", "key": cache_key},
            )
        outbound = self._build_cached_response(enriched, method=method)
        outbound.background = response.background
        return outbound

    async def _prepare_response(
        self, response: Response, policy: CachePolicy, path_template: str
    ) -> CacheEntry | None:
        if response.status_code >= 400:
            return None
        body = await self._consume_response_body(response)
        headers = dict(response.headers)
        last_modified_raw = headers.get("Last-Modified")
        last_modified_dt = self._resolve_last_modified(last_modified_raw)
        if last_modified_dt is None:
            last_modified_dt = datetime.now(timezone.utc)
        last_modified_dt = last_modified_dt.replace(microsecond=0)
        last_modified_value = format_datetime(last_modified_dt, usegmt=True)
        etag_value = self._generate_etag(body)

        headers.update(
            {
                "ETag": etag_value,
                "Last-Modified": last_modified_value,
                "Cache-Control": policy.cache_control,
            }
        )
        if self._vary_headers:
            headers["Vary"] = ", ".join(self._vary_headers)
        headers["Content-Length"] = str(len(body))

        entry = CacheEntry(
            key="",
            path_template=path_template,
            status_code=response.status_code,
            body=body,
            headers=headers,
            media_type=response.media_type,
            etag=etag_value,
            last_modified=last_modified_value,
            last_modified_ts=int(last_modified_dt.timestamp()),
            cache_control=policy.cache_control,
            vary=self._vary_headers,
            created_at=0.0,
            expires_at=None,
        )
        return entry

    async def _consume_response_body(self, response: Response) -> bytes:
        if hasattr(response, "body_iterator"):
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                body += chunk
            response.body_iterator = iter([body])  # type: ignore[attr-defined]
            return body
        return response.body  # type: ignore[return-value]

    def _generate_etag(self, body: bytes) -> str:
        from hashlib import blake2b, md5

        digest = blake2b(body, digest_size=16).hexdigest()
        if self._etag_strategy == "weak":
            return f'W/"{digest}"'
        if self._etag_strategy == "md5":  # convenience for testing fallback
            return f'"{md5(body).hexdigest()}"'
        return f'"{digest}"'

    def _build_cache_key(self, request: Request, path_template: str, method: str) -> str:
        path_params = {key: str(value) for key, value in request.path_params.items()}
        auth_token = "|".join(
            filter(
                None,
                [
                    request.headers.get("authorization"),
                    request.headers.get("x-api-key"),
                ],
            )
        )
        auth_variant = resolve_auth_variant(auth_token or None)
        return build_cache_key(
            method=method,
            path_template=path_template,
            query_string=request.url.query,
            path_params=path_params,
            auth_variant=auth_variant,
        )

    def _build_cached_response(self, entry: CacheEntry, *, method: str = "GET") -> Response:
        headers = dict(entry.headers)
        headers["Age"] = str(max(0, int(self._cache_age(entry))))
        body = entry.body if method.upper() != "HEAD" else b""
        return Response(
            content=body,
            status_code=entry.status_code,
            media_type=entry.media_type,
            headers=headers,
        )

    def _build_not_modified_response(self, entry: CacheEntry) -> Response:
        headers = {
            "ETag": entry.etag,
            "Last-Modified": entry.last_modified,
            "Cache-Control": entry.cache_control,
        }
        if entry.vary:
            headers["Vary"] = ", ".join(entry.vary)
        headers["Age"] = str(max(0, int(self._cache_age(entry))))
        return Response(status_code=304, headers=headers)

    def _cache_age(self, entry: CacheEntry) -> float:
        now = datetime.now(timezone.utc).timestamp()
        return max(0.0, now - entry.created_at)

    def _is_not_modified(self, request: Request, entry: CacheEntry) -> bool:
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and self._etag_matches(if_none_match, entry.etag):
            return True

        if_modified_since = request.headers.get("if-modified-since")
        if if_modified_since:
            try:
                candidate = parsedate_to_datetime(if_modified_since)
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None:
                if candidate.tzinfo is None:
                    candidate = candidate.replace(tzinfo=timezone.utc)
                if entry.last_modified_ts <= int(candidate.timestamp()):
                    return True
        return False

    def _etag_matches(self, header_value: str, etag: str) -> bool:
        candidates = [item.strip() for item in header_value.split(",") if item.strip()]
        if "*" in candidates:
            return True
        return etag in candidates

    def _apply_headers(
        self, response: Response, path_template: str, *, method: str
    ) -> Response:
        policy = self._policy_for(path_template)
        if not hasattr(response, "body"):
            response.headers.setdefault("Cache-Control", policy.cache_control)
            if self._vary_headers:
                response.headers.setdefault("Vary", ", ".join(self._vary_headers))
            return self._ensure_head_semantics(response, method)

        body = response.body if isinstance(response.body, (bytes, bytearray)) else b""
        last_modified_dt = self._resolve_last_modified(response.headers.get("Last-Modified"))
        if last_modified_dt is None:
            last_modified_dt = datetime.now(timezone.utc)
        last_modified_dt = last_modified_dt.replace(microsecond=0)
        last_modified_value = format_datetime(last_modified_dt, usegmt=True)
        if "ETag" not in response.headers:
            response.headers["ETag"] = self._generate_etag(body)
        response.headers.setdefault("Last-Modified", last_modified_value)
        response.headers.setdefault("Cache-Control", policy.cache_control)
        if self._vary_headers:
            response.headers.setdefault("Vary", ", ".join(self._vary_headers))
        return self._ensure_head_semantics(response, method)

    def _ensure_head_semantics(self, response: Response, method: str) -> Response:
        if method.upper() != "HEAD":
            return response
        response.body = b""
        header_names = {key.lower() for key in response.headers}
        if "content-length" not in header_names:
            response.headers["Content-Length"] = "0"
        return response

    def _resolve_last_modified(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    async def _invalidate_related(self, path_template: str) -> None:
        prefix = f"GET:{path_template}"
        try:
            await self._cache.invalidate_prefix(prefix)
        except Exception:  # pragma: no cover - defensive
            if not self._cache.fail_open:
                raise
            logger.warning(
                "Cache invalidation failed", extra={"event": "cache.error", "prefix": prefix}
            )
