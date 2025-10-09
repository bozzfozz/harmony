"""HTTP response caching utilities for Harmony."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, Mapping
from urllib.parse import parse_qsl

from app.logging import get_logger
from app.logging_events import log_event

logger = get_logger(__name__)


TimeProvider = Callable[[], float]


@dataclass(slots=True)
class CacheEntry:
    """A cached HTTP response."""

    key: str
    path_template: str
    status_code: int
    body: bytes
    headers: dict[str, str]
    media_type: str | None
    etag: str
    last_modified: str
    last_modified_ts: int
    cache_control: str
    vary: tuple[str, ...]
    created_at: float
    expires_at: float | None
    ttl: float
    stale_while_revalidate: float | None
    stale_expires_at: float | None

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def is_stale(self, now: float) -> bool:
        return self.stale_expires_at is not None and now >= self.stale_expires_at


class ResponseCache:
    """In-memory TTL cache with LRU eviction for HTTP responses."""

    def __init__(
        self,
        *,
        max_items: int,
        default_ttl: float,
        fail_open: bool = True,
        time_func: TimeProvider | None = None,
        write_through: bool = True,
        log_evictions: bool = True,
    ) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        if default_ttl < 0:
            raise ValueError("default_ttl must be non-negative")
        self._max_items = max_items
        self._default_ttl = default_ttl
        self._fail_open = fail_open
        self._cache: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._lock = asyncio.Lock()
        self._now: TimeProvider = time_func or time.time
        self._write_through = write_through
        self._log_evictions = log_evictions

    @property
    def default_ttl(self) -> float:
        return self._default_ttl

    async def get(self, key: str) -> CacheEntry | None:
        try:
            async with self._lock:
                entry = self._cache.get(key)
                if entry is None:
                    self._log_operation("miss", "miss", key_hash=key)
                    return None
                now = self._now()
                if entry.is_expired(now):
                    self._cache.pop(key, None)
                    self._log_operation(
                        "expired",
                        "expired",
                        key_hash=key,
                        path=entry.path_template,
                        age_s=round(now - entry.created_at, 3),
                    )
                    return None
                self._cache.move_to_end(key)
                self._log_operation(
                    "hit",
                    "hit",
                    key_hash=key,
                    path=entry.path_template,
                )
                return entry
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error", key_hash=key)
                return None
            raise

    async def set(
        self, key: str, entry: CacheEntry, *, ttl: float | None = None
    ) -> None:
        ttl_value = self._resolve_ttl(ttl)
        try:
            async with self._lock:
                now = self._now()
                expires_at = now + ttl_value
                entry.key = key
                entry.created_at = now
                entry.expires_at = expires_at
                entry.ttl = ttl_value
                stale = entry.stale_while_revalidate
                if stale is not None:
                    entry.stale_expires_at = expires_at + max(0.0, stale)
                else:
                    entry.stale_expires_at = None
                if key in self._cache:
                    self._cache.pop(key)
                self._cache[key] = entry
                self._enforce_limit()
            self._log_operation(
                "store",
                "stored",
                key_hash=key,
                ttl_s=ttl_value,
                path=entry.path_template,
            )
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error", key_hash=key)
                return
            raise

    async def invalidate(self, key: str) -> None:
        try:
            async with self._lock:
                if key in self._cache:
                    self._cache.pop(key, None)
                    self._log_operation("invalidate", "invalidated", key_hash=key)
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error", key_hash=key)
                return
            raise

    async def invalidate_prefix(
        self,
        prefix: str,
        *,
        reason: str | None = None,
        entity_id: str | None = None,
        path: str | None = None,
        pattern: str | None = None,
    ) -> int:
        try:
            async with self._lock:
                keys = [key for key in self._cache if key.startswith(prefix)]
                removed = [self._cache.pop(key, None) for key in keys]
                removed = [entry for entry in removed if entry is not None]
                count = len(removed)
            operation = (
                "evict" if any((reason, entity_id, path, pattern)) else "invalidate"
            )
            status = "evicted" if count else "noop"
            fields: dict[str, object] = {
                "key_hash": prefix,
                "count": count,
            }
            if path:
                fields["path"] = path
            if pattern:
                fields["pattern"] = pattern
            if reason:
                fields["reason"] = reason
            if entity_id:
                fields["entity_id"] = entity_id
            if removed:
                template = removed[0].path_template
                if template:
                    fields.setdefault("path_template", template)
            self._log_operation(operation, status, **fields)
            return count
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error", key_hash=prefix)
                return 0
            raise

    async def invalidate_path(
        self,
        path: str,
        *,
        method: str = "GET",
        reason: str | None = None,
        entity_id: str | None = None,
    ) -> int:
        normalized = self._normalize_path(path)
        method_key = method.upper()
        prefix = f"{method_key}:{normalized}"
        try:
            async with self._lock:
                keys_to_remove: list[str] = []
                removed_entries: list[CacheEntry] = []
                for key, entry in self._cache.items():
                    if not key.startswith(method_key):
                        continue
                    if key.startswith(prefix) or self._path_matches_entry(
                        normalized, entry
                    ):
                        keys_to_remove.append(key)
                for key in keys_to_remove:
                    removed = self._cache.pop(key, None)
                    if removed is not None:
                        removed_entries.append(removed)
                count = len(removed_entries)
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error", key_hash=prefix)
                return 0
            raise

        operation = "evict" if any((reason, entity_id)) else "invalidate"
        status = "evicted" if count else "noop"
        fields: dict[str, object] = {
            "key_hash": prefix,
            "count": count,
            "path": normalized,
        }
        if reason:
            fields["reason"] = reason
        if entity_id:
            fields["entity_id"] = entity_id
        if removed_entries:
            template = removed_entries[0].path_template
            if template:
                fields.setdefault("path_template", template)
        self._log_operation(operation, status, **fields)
        return count

    async def invalidate_pattern(
        self,
        pattern: str,
        *,
        reason: str | None = None,
        entity_id: str | None = None,
    ) -> int:
        try:
            compiled = re.compile(pattern)
        except re.error:
            return await self.invalidate_prefix(
                pattern,
                reason=reason,
                entity_id=entity_id,
                pattern=pattern,
            )

        try:
            async with self._lock:
                matching_keys = [key for key in self._cache if compiled.search(key)]
                removed_entries = [self._cache.pop(key, None) for key in matching_keys]
                removed_entries = [
                    entry for entry in removed_entries if entry is not None
                ]
                count = len(removed_entries)
            operation = "evict" if reason or entity_id else "invalidate"
            status = "evicted" if count else "noop"
            fields: dict[str, object] = {
                "pattern": pattern,
                "count": count,
                "key_hash": pattern,
            }
            if reason:
                fields["reason"] = reason
            if entity_id:
                fields["entity_id"] = entity_id
            if removed_entries:
                template = removed_entries[0].path_template
                if template:
                    fields.setdefault("path_template", template)
            self._log_operation(operation, status, **fields)
            return count
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error", pattern=pattern)
                return 0
            raise

    async def clear(self) -> None:
        try:
            async with self._lock:
                if not self._cache:
                    return
                self._cache.clear()
            self._log_operation("clear", "cleared")
        except Exception:
            if self._fail_open:
                self._log_operation("error", "error")
                return
            raise

    def _enforce_limit(self) -> None:
        while len(self._cache) > self._max_items:
            key, _ = self._cache.popitem(last=False)
            self._log_operation("evict", "evicted", key_hash=key)

    def _resolve_ttl(self, ttl: float | None) -> float:
        if ttl is None:
            return self._default_ttl
        return max(0.0, ttl)

    @property
    def fail_open(self) -> bool:
        return self._fail_open

    @property
    def write_through(self) -> bool:
        return self._write_through

    @property
    def log_evictions(self) -> bool:
        return self._log_evictions

    @staticmethod
    def _normalize_path(path: str) -> str:
        trimmed = (path or "").strip()
        if not trimmed:
            return "/"
        if not trimmed.startswith("/"):
            return f"/{trimmed}"
        return trimmed

    def _path_matches_entry(self, path: str, entry: CacheEntry) -> bool:
        template = self._normalize_path(entry.path_template)
        if template == path:
            return True
        if "{" not in template or "}" not in template:
            return False
        pattern = _compile_path_template(template)
        return pattern.fullmatch(path) is not None

    def _log_operation(self, operation: str, status: str, **fields: object) -> None:
        if operation == "evict" and not self._log_evictions:
            return
        _log_cache_event(operation, status, **fields)


def _hash_from_items(items: Iterable[tuple[str, str]]) -> str:
    if not items:
        return "0"
    serialised = json.dumps(list(items), separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.blake2b(serialised.encode("utf-8"), digest_size=16)
    return digest.hexdigest()


def build_query_hash(raw_query: str) -> str:
    """Build a deterministic hash for a query string."""

    if not raw_query:
        return "0"
    pairs = parse_qsl(raw_query, keep_blank_values=True)
    sorted_pairs = sorted((key, value) for key, value in pairs)
    return _hash_from_items(sorted_pairs)


def build_path_param_hash(path_params: Mapping[str, str]) -> str:
    if not path_params:
        return "0"
    sorted_items = sorted((str(key), str(value)) for key, value in path_params.items())
    return _hash_from_items(sorted_items)


def build_cache_key(
    *,
    method: str,
    path_template: str,
    query_string: str,
    path_params: Mapping[str, str],
    auth_variant: str,
) -> str:
    """Construct the cache key for a response."""

    query_hash = build_query_hash(query_string)
    path_hash = build_path_param_hash(path_params)
    segments = [
        method.upper(),
        path_template,
        path_hash,
        query_hash,
        auth_variant or "anon",
    ]
    return ":".join(segments)


def resolve_auth_variant(authorization_header: str | None) -> str:
    if not authorization_header:
        return "anon"
    digest = hashlib.blake2b(authorization_header.encode("utf-8"), digest_size=16)
    return digest.hexdigest()


PLAYLIST_LIST_CACHE_PREFIX = "cache:playlists:list"
PLAYLIST_DETAIL_CACHE_PREFIX = "cache:playlists:detail"


def playlist_filters_hash(query_string: str) -> str:
    """Return a stable hash for playlist listing filters."""

    return build_query_hash(query_string)


def playlist_list_cache_key(
    *, query_string: str = "", filters_hash: str | None = None
) -> str:
    """Construct the canonical cache key for playlist collection responses."""

    resolved_hash = (
        filters_hash
        if filters_hash is not None
        else playlist_filters_hash(query_string)
    )
    return f"{PLAYLIST_LIST_CACHE_PREFIX}:{resolved_hash}"


def playlist_detail_cache_key(playlist_id: str) -> str:
    """Construct the canonical cache key for a playlist detail response."""

    normalized = playlist_id.strip()
    return (
        f"{PLAYLIST_DETAIL_CACHE_PREFIX}:{normalized}"
        if normalized
        else f"{PLAYLIST_DETAIL_CACHE_PREFIX}:"
    )


def artist_cache_templates(base_path: str | None) -> tuple[str, ...]:
    """Return canonical cache templates for artist resources."""

    detail_template = "/artists/{artist_key}"
    templates = [detail_template]
    if base_path:
        normalized = base_path.rstrip("/")
        if normalized and normalized != "/":
            templates.append(f"{normalized}{detail_template}")
    seen: set[str] = set()
    ordered: list[str] = []
    for template in templates:
        if template not in seen:
            ordered.append(template)
            seen.add(template)
    return tuple(ordered)


async def bust_artist_cache(
    cache: "ResponseCache" | None,
    *,
    artist_key: str,
    base_path: str | None = None,
    reason: str = "manual",
    entity_id: str | None = None,
) -> int:
    """Invalidate cached responses associated with an artist resource."""

    if cache is None or not getattr(cache, "write_through", True):
        return 0

    path_hash = build_path_param_hash({"artist_key": artist_key})
    total = 0
    for template in artist_cache_templates(base_path):
        prefix = f"GET:{template}:{path_hash}:"
        total += await cache.invalidate_prefix(
            prefix,
            reason=reason,
            entity_id=entity_id or artist_key,
            path=template,
        )
    return total


def _log_cache_event(operation: str, status: str, **fields: object) -> None:
    legacy_payload = dict(fields)
    legacy_payload.setdefault("component", "service.cache")
    legacy_payload["status"] = status
    log_event(
        logger,
        f"cache.{operation}",
        **legacy_payload,
    )
    log_event(
        logger,
        "service.cache",
        component="service.cache",
        operation=operation,
        status=status,
        **fields,
    )


@lru_cache(maxsize=512)
def _compile_path_template(template: str) -> re.Pattern[str]:
    normalized = ResponseCache._normalize_path(template)
    pattern_parts: list[str] = []
    index = 0
    length = len(normalized)
    while index < length:
        char = normalized[index]
        if char == "{":
            end = normalized.find("}", index + 1)
            if end == -1:
                pattern_parts.append(re.escape(normalized[index:]))
                break
            content = normalized[index + 1 : end]
            converter: str | None = None
            if ":" in content:
                _, converter = content.split(":", 1)
            if converter == "path":
                pattern_parts.append(".+")
            else:
                pattern_parts.append("[^/]+")
            index = end + 1
            continue
        pattern_parts.append(re.escape(char))
        index += 1
    pattern = "^" + "".join(pattern_parts) + "$"
    return re.compile(pattern)
