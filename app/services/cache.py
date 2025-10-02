"""HTTP response caching utilities for Harmony."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
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

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class ResponseCache:
    """In-memory TTL cache with LRU eviction for HTTP responses."""

    def __init__(
        self,
        *,
        max_items: int,
        default_ttl: float,
        fail_open: bool = True,
        time_func: TimeProvider | None = None,
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

    @property
    def default_ttl(self) -> float:
        return self._default_ttl

    async def get(self, key: str) -> CacheEntry | None:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                _log_cache_event("miss", "miss", key_hash=key)
                return None
            now = self._now()
            if entry.is_expired(now):
                self._cache.pop(key, None)
                _log_cache_event(
                    "expired",
                    "expired",
                    key_hash=key,
                    path=entry.path_template,
                    age_s=round(now - entry.created_at, 3),
                )
                return None
            self._cache.move_to_end(key)
            _log_cache_event(
                "hit",
                "hit",
                key_hash=key,
                path=entry.path_template,
            )
            return entry

    async def set(self, key: str, entry: CacheEntry, *, ttl: float | None = None) -> None:
        ttl_value = self._resolve_ttl(ttl)
        async with self._lock:
            now = self._now()
            expires_at = now + ttl_value if ttl_value > 0 else None
            entry.key = key
            entry.created_at = now
            entry.expires_at = expires_at
            if key in self._cache:
                self._cache.pop(key)
            self._cache[key] = entry
            self._enforce_limit()
        _log_cache_event(
            "store",
            "stored",
            key_hash=key,
            ttl_s=ttl_value,
            path=entry.path_template,
        )

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            if key in self._cache:
                self._cache.pop(key, None)
                _log_cache_event("invalidate", "invalidated", key_hash=key)

    async def invalidate_prefix(self, prefix: str) -> int:
        async with self._lock:
            keys = [key for key in self._cache if key.startswith(prefix)]
            for key in keys:
                self._cache.pop(key, None)
            if keys:
                _log_cache_event(
                    "invalidate",
                    "invalidated",
                    key_hash=prefix,
                    count=len(keys),
                )
            return len(keys)

    async def clear(self) -> None:
        async with self._lock:
            if not self._cache:
                return
            self._cache.clear()
        _log_cache_event("clear", "cleared")

    def _enforce_limit(self) -> None:
        while len(self._cache) > self._max_items:
            key, _ = self._cache.popitem(last=False)
            _log_cache_event("evict", "evicted", key_hash=key)

    def _resolve_ttl(self, ttl: float | None) -> float:
        if ttl is None:
            return self._default_ttl
        return max(0.0, ttl)

    @property
    def fail_open(self) -> bool:
        return self._fail_open


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
    segments = [method.upper(), path_template, path_hash, query_hash, auth_variant or "anon"]
    return ":".join(segments)


def resolve_auth_variant(authorization_header: str | None) -> str:
    if not authorization_header:
        return "anon"
    digest = hashlib.blake2b(authorization_header.encode("utf-8"), digest_size=16)
    return digest.hexdigest()


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
