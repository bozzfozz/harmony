"""OpenAPI example payloads for artist workflow endpoints."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

ARTIST_COLLECTION_EXAMPLE: Mapping[str, Any] = {
    "items": [
        {
            "artist_key": "spotify:artist:1",
            "priority": 5,
            "last_enqueued_at": "2024-03-01T11:45:00Z",
            "cooldown_until": None,
            "created_at": "2024-02-10T08:00:00Z",
            "updated_at": "2024-03-01T11:45:00Z",
        }
    ],
    "total": 1,
    "limit": 25,
    "offset": 0,
}

ARTIST_DETAIL_EXAMPLE: Mapping[str, Any] = {
    "id": 42,
    "artist_key": "spotify:artist:1",
    "source": "spotify",
    "source_id": "1Xyo4u8uXC1ZmMpatF05PJ",
    "name": "Test Artist",
    "genres": ["indie", "shoegaze"],
    "images": [
        "https://images.example/harmony/artist-1/640x640.jpg",
        "https://images.example/harmony/artist-1/320x320.jpg",
    ],
    "popularity": 67,
    "metadata": {"followers": 1203456, "label": "Harmony Records"},
    "version": "2024-03-01T12:00:00Z",
    "etag": '"artist-sync-7b4a5c90"',
    "updated_at": "2024-03-01T12:00:00Z",
    "created_at": "2023-11-12T09:15:00Z",
    "releases": [
        {
            "id": 101,
            "artist_key": "spotify:artist:1",
            "source": "spotify",
            "source_id": "6s84u2TUpR3wdUv4NgKA2j",
            "title": "Harmony Release",
            "release_date": "2024-03-01",
            "release_type": "album",
            "total_tracks": 10,
            "version": None,
            "etag": '"release-cc928fb6"',
            "updated_at": "2024-03-01T12:00:00Z",
            "created_at": "2024-03-01T12:00:00Z",
        }
    ],
}

ARTIST_ENQUEUE_EXAMPLE: Mapping[str, Any] = {
    "job_id": 9182736,
    "job_type": "artist_sync",
    "status": "pending",
    "priority": 10,
    "available_at": "2024-03-01T12:00:00Z",
    "already_enqueued": False,
}


def _set_json_example(
    paths: Mapping[str, Any],
    path: str | None,
    method: str,
    status_code: str,
    example: Mapping[str, Any],
) -> None:
    if not path:
        return
    item = paths.get(path)
    if not isinstance(item, dict):
        return
    operation = item.get(method)
    if not isinstance(operation, dict):
        return
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return
    response = responses.get(status_code)
    if not isinstance(response, dict):
        return
    content = response.setdefault("content", {}).setdefault("application/json", {})
    content.setdefault("example", deepcopy(example))


def apply_artist_examples(
    schema: dict[str, Any],
    *,
    collection_path: str | None = None,
    watchlist_path: str | None = None,
    detail_path: str | None,
    enqueue_path: str | None,
) -> None:
    """Attach standard examples to artist-related OpenAPI operations."""

    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return

    if collection_path:
        _set_json_example(paths, collection_path, "get", "200", ARTIST_COLLECTION_EXAMPLE)
    if watchlist_path:
        _set_json_example(paths, watchlist_path, "get", "200", ARTIST_COLLECTION_EXAMPLE)
    _set_json_example(paths, detail_path, "get", "200", ARTIST_DETAIL_EXAMPLE)
    _set_json_example(paths, enqueue_path, "post", "202", ARTIST_ENQUEUE_EXAMPLE)
