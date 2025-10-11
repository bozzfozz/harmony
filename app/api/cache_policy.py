"""Shared cache policy metadata for API documentation."""

from __future__ import annotations

from typing import Final, Mapping

_CACHE_HEADERS_DESCRIPTION: Final[str] = (
    "Responses leverage conditional request caching via ETag and Last-Modified headers."
)

_CACHE_POLICY_HEADERS: Final[Mapping[str, Mapping[str, object]]] = {
    "Cache-Control": {
        "description": "Cache directives for the representation.",
        "schema": {"type": "string"},
    },
    "ETag": {
        "description": "Strong or weak entity tag identifying the representation.",
        "schema": {"type": "string"},
    },
    "Last-Modified": {
        "description": "Timestamp of the most recent modification.",
        "schema": {"type": "string", "format": "date-time"},
    },
    "Vary": {
        "description": (
            "Headers that influence cache variations, including Authorization, "
            "X-API-Key, Origin and Accept-Encoding."
        ),
        "schema": {"type": "string"},
    },
    "Age": {
        "description": "Approximate number of seconds the response has been cached.",
        "schema": {"type": "integer", "minimum": 0},
    },
}

CACHEABLE_RESPONSES: Final[Mapping[int, Mapping[str, object]]] = {
    200: {
        "description": (
            "Successful response with cache metadata. Subsequent cache hits may "
            "include an Age header. The `/spotify/status` endpoint bypasses the "
            "response cache so credential changes are reflected immediately."
        ),
        "headers": {key: value for key, value in _CACHE_POLICY_HEADERS.items() if key != "Age"},
    },
    304: {
        "description": _CACHE_HEADERS_DESCRIPTION,
        "headers": _CACHE_POLICY_HEADERS,
    },
}

__all__ = ["CACHEABLE_RESPONSES"]
