"""HTTP conditional request caching middleware."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
import hashlib
import re

from fastapi import Request
from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import CacheMiddlewareConfig, CacheRule
from app.logging import get_logger
from app.logging_events import log_event
from app.services.cache import (
    CacheEntry,
    ResponseCache,
    build_cache_key,
    build_query_hash,
    playlist_detail_cache_key,
    playlist_filters_hash,
    playlist_list_cache_key,
    resolve_auth_variant,
)

_logger = get_logger(__name__)


def _compile_rules(
    rules: Iterable[CacheRule],
) -> tuple[tuple[re.Pattern[str], CacheRule], ...]:
    compiled: list[tuple[re.Pattern[str], CacheRule]] = []
    for rule in rules:
        pattern = rule.pattern
        if not pattern:
            continue
        try:
            compiled.append((re.compile(pattern), rule))
        except re.error:
            # Treat invalid regex as literal string match.
            escaped = re.escape(pattern)
            compiled.append((re.compile(escaped), rule))
    return tuple(compiled)


_PLAYLIST_LIST_PATTERN = re.compile(r"^/(?:[^/]+/)*spotify/playlists$")
_PLAYLIST_DETAIL_PATTERN = re.compile(
    r"^/(?:[^/]+/)*spotify/playlists/(?:\{[^/]+\}|[^/]+)(?:/tracks)?$"
)


class CacheMiddleware(BaseHTTPMiddleware):
    """Serve cached responses for cacheable routes using ETag semantics."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        cache: ResponseCache,
        config: CacheMiddlewareConfig,
        vary_headers: tuple[str, ...] = (
            "Authorization",
            "X-API-Key",
            "Origin",
            "Accept-Encoding",
        ),
    ) -> None:
        super().__init__(app)
        self._cache = cache
        self._config = config
        self._vary_headers = vary_headers
        self._rules = _compile_rules(config.cacheable_paths)

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._config.enabled:
            return await call_next(request)

        method = request.method.upper()
        if method not in {"GET", "HEAD"}:
            response = await call_next(request)
            return response

        path_template = self._path_template(request)
        raw_path = request.url.path
        base_path = getattr(request.app.state, "api_base_path", "") or ""
        trimmed_path = self._trim_base_path(raw_path, base_path)
        rule = self._match_rule(path_template, raw_path, trimmed_path)
        if rule is None:
            response = await call_next(request)
            return self._ensure_head_semantics(self._ensure_headers(response), method)

        cache_key = self._build_cache_key(
            request,
            path_template,
            raw_path=raw_path,
            trimmed_path=trimmed_path,
        )
        try:
            cached = await self._cache.get(cache_key)
        except Exception:  # pragma: no cover - defensive guard
            log_event(
                _logger,
                "cache.error",
                component="middleware.cache",
                status="error",
                path=path_template,
                key_hash=cache_key,
            )
            if self._config.fail_open:
                cached = None
            else:
                raise
        if cached is not None:
            if self._is_not_modified(request, cached):
                log_event(
                    _logger,
                    "cache.not_modified",
                    component="middleware.cache",
                    status="hit",
                    path=path_template,
                    method=method,
                    key_hash=cache_key,
                )
                return self._build_not_modified_response(cached)
            log_event(
                _logger,
                "cache.hit",
                component="middleware.cache",
                status="hit",
                path=path_template,
                method=method,
                key_hash=cache_key,
            )
            return self._build_cached_response(cached, method=method)

        response = await call_next(request)
        return await self._store_and_return(
            request,
            response,
            cache_key,
            path_template,
            rule=rule,
            method=method,
        )

    def _path_template(self, request: Request) -> str:
        route = request.scope.get("route")
        return getattr(route, "path_format", request.url.path)

    def _match_rule(
        self,
        path_template: str,
        raw_path: str,
        trimmed_path: str,
    ) -> CacheRule | None:
        if not self._rules:
            return None
        candidates = {path_template, raw_path, trimmed_path}
        for pattern, rule in self._rules:
            if any(pattern.fullmatch(candidate) for candidate in candidates):
                return rule
        return None

    @staticmethod
    def _trim_base_path(path: str, base_path: str) -> str:
        if not base_path or base_path == "/":
            return path
        normalized = base_path.rstrip("/") or "/"
        if path == normalized:
            return "/"
        prefix = f"{normalized}/"
        if path.startswith(prefix):
            remainder = path[len(normalized) :]
            return remainder or "/"
        return path

    def _build_cache_key(
        self,
        request: Request,
        path_template: str,
        *,
        raw_path: str,
        trimmed_path: str,
    ) -> str:
        special = self._build_playlist_cache_key(
            request,
            path_template=path_template,
            raw_path=raw_path,
            trimmed_path=trimmed_path,
        )
        if special is not None:
            return special

        path_params = {key: str(value) for key, value in request.path_params.items()}
        auth_header = request.headers.get("authorization") or request.headers.get("x-api-key")
        auth_variant = resolve_auth_variant(auth_header)
        method = "GET" if request.method.upper() == "HEAD" else request.method
        return build_cache_key(
            method=method,
            path_template=path_template,
            query_string=request.url.query,
            path_params=path_params,
            auth_variant=auth_variant,
        )

    def _build_playlist_cache_key(
        self,
        request: Request,
        *,
        path_template: str,
        raw_path: str,
        trimmed_path: str,
    ) -> str | None:
        candidates = {path_template, raw_path, trimmed_path}
        playlist_id = request.path_params.get("playlist_id")
        for candidate in candidates:
            if not candidate:
                continue
            normalized = candidate.rstrip("/") or "/"
            if _PLAYLIST_LIST_PATTERN.fullmatch(normalized):
                filters_hash = playlist_filters_hash(request.url.query)
                return playlist_list_cache_key(filters_hash=filters_hash)
            if _PLAYLIST_DETAIL_PATTERN.fullmatch(normalized) and playlist_id:
                auth_header = request.headers.get("authorization") or request.headers.get(
                    "x-api-key"
                )
                auth_variant = resolve_auth_variant(auth_header)
                query_hash = build_query_hash(request.url.query)
                method = "GET" if request.method.upper() == "HEAD" else request.method.upper()
                detail_prefix = playlist_detail_cache_key(str(playlist_id))
                return f"{detail_prefix}:{method}:{query_hash}:{auth_variant}"
        return None

    async def _store_and_return(
        self,
        request: Request,
        response: Response,
        cache_key: str,
        path_template: str,
        *,
        rule: CacheRule,
        method: str,
    ) -> Response:
        if response.status_code >= 400 or method != "GET":
            enriched = self._ensure_headers(response, rule)
            return self._ensure_head_semantics(enriched, method)

        ttl, stale = self._resolve_durations(rule)
        entry = await self._prepare_entry(response, path_template, ttl=ttl, stale=stale)
        if entry is None:
            enriched = self._ensure_headers(response, rule)
            return self._ensure_head_semantics(enriched, method)

        try:
            await self._cache.set(cache_key, entry, ttl=float(ttl))
        except Exception:  # pragma: no cover - defensive guard
            log_event(
                _logger,
                "cache.store_failed",
                component="middleware.cache",
                status="error",
                path=path_template,
                key_hash=cache_key,
            )
            if self._config.fail_open:
                enriched = self._ensure_headers(response, rule)
                return self._ensure_head_semantics(enriched, method)
            raise

        log_event(
            _logger,
            "cache.store",
            component="middleware.cache",
            status="stored",
            path=path_template,
            key_hash=cache_key,
        )
        cached_response = self._build_cached_response(entry, method=method)
        cached_response.background = response.background
        return cached_response

    async def _prepare_entry(
        self,
        response: Response,
        path_template: str,
        *,
        ttl: int,
        stale: int | None,
    ) -> CacheEntry | None:
        body = await self._read_body(response)
        if body is None:
            return None

        now = datetime.now(UTC).replace(microsecond=0)
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            try:
                parsed = parsedate_to_datetime(last_modified)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                now = parsed.astimezone(UTC).replace(microsecond=0)

        existing_etag = response.headers.get("ETag")
        if existing_etag:
            candidates = [value.strip() for value in existing_etag.split(",") if value.strip()]
            etag = candidates[0] if candidates else self._generate_etag(body)
        else:
            etag = self._generate_etag(body)
        headers = dict(response.headers)
        headers["ETag"] = etag
        headers["Last-Modified"] = format_datetime(now, usegmt=True)
        headers.setdefault("Cache-Control", self._build_cache_control(ttl, stale))
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
            etag=etag,
            last_modified=headers["Last-Modified"],
            last_modified_ts=int(now.timestamp()),
            cache_control=headers.get("Cache-Control", ""),
            vary=self._vary_headers,
            created_at=0.0,
            expires_at=None,
            ttl=float(ttl),
            stale_while_revalidate=float(stale) if stale is not None else None,
            stale_expires_at=None,
        )
        return entry

    async def _read_body(self, response: Response) -> bytes | None:
        if hasattr(response, "body_iterator"):
            iterator = getattr(response, "body_iterator")  # type: ignore[attr-defined]
            if iterator is not None:
                chunks = []
                async for chunk in iterator:
                    chunk_bytes = chunk if isinstance(chunk, bytes | bytearray) else bytes(chunk)
                    chunks.append(bytes(chunk_bytes))
                if not chunks:
                    chunks.append(b"")
                data = b"".join(chunks)
                response.body = data
                response.body_iterator = iterate_in_threadpool(iter(chunks))  # type: ignore[attr-defined]
                return data
        body = response.body
        if body is None:
            return None
        return body if isinstance(body, bytes | bytearray) else bytes(body)

    def _generate_etag(self, body: bytes) -> str:
        digest = hashlib.blake2b(body, digest_size=16).hexdigest()
        if self._config.etag_strategy == "weak":
            return f'W/"{digest}"'
        return f'"{digest}"'

    def _ensure_headers(self, response: Response, rule: CacheRule | None = None) -> Response:
        if self._vary_headers:
            response.headers.setdefault("Vary", ", ".join(self._vary_headers))
        if self._requires_no_store(response):
            response.headers["Cache-Control"] = "no-store"
            return response
        ttl, stale = self._resolve_durations(rule)
        response.headers.setdefault("Cache-Control", self._build_cache_control(ttl, stale))
        return response

    @staticmethod
    def _requires_no_store(response: Response) -> bool:
        media_type = (response.media_type or "").lower()
        if media_type.startswith("text/html"):
            return True
        content_type = response.headers.get("content-type")
        if content_type and "text/html" in content_type.lower():
            return True
        return False

    def _ensure_head_semantics(self, response: Response, method: str) -> Response:
        if method != "HEAD":
            return response
        response.body = b""
        if "content-length" not in {key.lower() for key in response.headers}:
            response.headers["Content-Length"] = "0"
        return response

    def _build_cached_response(self, entry: CacheEntry, *, method: str) -> Response:
        headers = dict(entry.headers)
        headers["Age"] = str(max(0, int(self._age(entry))))
        body = entry.body if method != "HEAD" else b""
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
        headers["Age"] = str(max(0, int(self._age(entry))))
        return Response(status_code=304, headers=headers)

    def _age(self, entry: CacheEntry) -> float:
        now = datetime.now(UTC).timestamp()
        return max(0.0, now - entry.created_at)

    def _resolve_durations(self, rule: CacheRule | None) -> tuple[int, int | None]:
        ttl = rule.ttl if rule and rule.ttl is not None else self._config.default_ttl
        stale = (
            rule.stale_while_revalidate
            if rule and rule.stale_while_revalidate is not None
            else self._config.stale_while_revalidate
        )
        return max(0, int(ttl)), None if stale is None else max(0, int(stale))

    def _build_cache_control(self, ttl: int, stale: int | None) -> str:
        directives = [f"public, max-age={max(0, ttl)}"]
        if stale is not None:
            directives.append(f"stale-while-revalidate={max(0, stale)}")
        return ", ".join(directives)

    def _is_not_modified(self, request: Request, entry: CacheEntry) -> bool:
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and entry.etag in {
            candidate.strip() for candidate in if_none_match.split(",") if candidate.strip()
        }:
            return True

        if_modified_since = request.headers.get("if-modified-since")
        if if_modified_since:
            try:
                candidate = parsedate_to_datetime(if_modified_since)
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None:
                if candidate.tzinfo is None:
                    candidate = candidate.replace(tzinfo=UTC)
                if entry.last_modified_ts <= int(candidate.timestamp()):
                    return True
        return False


__all__ = ["CacheMiddleware"]
