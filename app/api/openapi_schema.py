"""Deterministic OpenAPI schema builder for the Harmony API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from typing import Any, NamedTuple

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import router_registry
from app.api.openapi_examples import apply_artist_examples
from app.config import AppConfig


class _SortKey(NamedTuple):
    primary: str
    secondary: str


def _normalise_server_url(url: str) -> str:
    if url == "/":
        return "/"
    if not url.startswith("/"):
        return f"/{url}" if url else "/"
    return url or "/"


def _sort_dict_recursive(mapping: MutableMapping[str, Any]) -> dict[str, Any]:
    sorted_items: dict[str, Any] = {}
    for key in sorted(mapping):
        sorted_items[key] = _sort_value(mapping[key])
    return sorted_items


def _sort_list(values: Iterable[Any]) -> list[Any]:
    return [_sort_value(item) for item in values]


def _sort_parameters(parameters: list[Any]) -> list[Any]:
    sortable: list[tuple[_SortKey, Any]] = []
    for item in parameters:
        if isinstance(item, Mapping):
            name = str(item.get("name", ""))
            location = str(item.get("in", ""))
            sortable.append((_SortKey(name, location), _sort_value(dict(item))))
        else:
            sortable.append((_SortKey("", ""), _sort_value(item)))
    return [
        value
        for _, value in sorted(sortable, key=lambda entry: (entry[0].primary, entry[0].secondary))
    ]


def _sort_security(security: list[Any]) -> list[Any]:
    sortable: list[tuple[str, Any]] = []
    for item in security:
        if isinstance(item, Mapping):
            normalised = _sort_dict_recursive(dict(item))
            serialised = json.dumps(
                normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            sortable.append((serialised, normalised))
        else:
            sortable.append(
                (
                    json.dumps(item, sort_keys=True, ensure_ascii=False),
                    _sort_value(item),
                )
            )
    return [value for _, value in sorted(sortable, key=lambda entry: entry[0])]


def _sort_tags(tags: Iterable[Any]) -> list[Any]:
    sortable: list[tuple[_SortKey, Any]] = []
    for raw in tags:
        if isinstance(raw, Mapping):
            item = _sort_dict_recursive(dict(raw))
            name = str(item.get("name", ""))
            description = str(item.get("description", ""))
            sortable.append((_SortKey(name, description), item))
        else:
            sortable.append((_SortKey(str(raw), ""), _sort_value(raw)))
    return [
        value
        for _, value in sorted(sortable, key=lambda entry: (entry[0].primary, entry[0].secondary))
    ]


def _sort_responses(responses: MutableMapping[str, Any]) -> dict[str, Any]:
    sorted_responses: dict[str, Any] = {}
    for status_code in sorted(responses, key=str):
        payload = responses[status_code]
        if isinstance(payload, MutableMapping):
            sorted_payload = _sort_dict_recursive(dict(payload))
            headers = sorted_payload.get("headers")
            if isinstance(headers, MutableMapping):
                sorted_payload["headers"] = _sort_dict_recursive(dict(headers))
            content = sorted_payload.get("content")
            if isinstance(content, MutableMapping):
                sorted_payload["content"] = _sort_dict_recursive(dict(content))
            sorted_responses[status_code] = sorted_payload
        else:
            sorted_responses[status_code] = _sort_value(payload)
    return sorted_responses


def _sort_operation(operation: MutableMapping[str, Any]) -> dict[str, Any]:
    sorted_operation = _sort_dict_recursive(operation)
    parameters = sorted_operation.get("parameters")
    if isinstance(parameters, list):
        sorted_operation["parameters"] = _sort_parameters(parameters)
    tags = sorted_operation.get("tags")
    if isinstance(tags, list):
        sorted_operation["tags"] = sorted(tags)
    security = sorted_operation.get("security")
    if isinstance(security, list):
        sorted_operation["security"] = _sort_security(security)
    responses = sorted_operation.get("responses")
    if isinstance(responses, MutableMapping):
        sorted_operation["responses"] = _sort_responses(responses)
    return sorted_operation


def _sort_path_item(item: MutableMapping[str, Any]) -> dict[str, Any]:
    sorted_item: dict[str, Any] = {}
    for method in sorted(item):
        payload = item[method]
        if isinstance(payload, MutableMapping):
            sorted_item[method] = _sort_operation(payload)
        else:
            sorted_item[method] = _sort_value(payload)
    return sorted_item


def _sort_paths(paths: MutableMapping[str, Any]) -> dict[str, Any]:
    sorted_paths: dict[str, Any] = {}
    for path, item in sorted(paths.items(), key=lambda entry: entry[0]):
        if isinstance(item, MutableMapping):
            sorted_paths[path] = _sort_path_item(item)
        else:
            sorted_paths[path] = _sort_value(item)
    return sorted_paths


def _sort_components(components: MutableMapping[str, Any]) -> dict[str, Any]:
    sorted_components = _sort_dict_recursive(components)
    for section in (
        "schemas",
        "responses",
        "parameters",
        "requestBodies",
        "headers",
        "securitySchemes",
    ):
        value = sorted_components.get(section)
        if isinstance(value, MutableMapping):
            sorted_components[section] = _sort_dict_recursive(value)
    return sorted_components


def _sort_value(value: Any) -> Any:
    if isinstance(value, MutableMapping):
        return _sort_dict_recursive(dict(value))
    if isinstance(value, Mapping):
        return _sort_dict_recursive(dict(value))
    if isinstance(value, list):
        return _sort_list(value)
    if isinstance(value, tuple):
        return tuple(_sort_list(value))
    return value


def _ensure_deterministic_structure(schema: MutableMapping[str, Any]) -> None:
    paths = schema.get("paths")
    if isinstance(paths, MutableMapping):
        schema["paths"] = _sort_paths(paths)
    components = schema.get("components")
    if isinstance(components, MutableMapping):
        schema["components"] = _sort_components(components)
    tags = schema.get("tags")
    if isinstance(tags, Iterable):
        schema["tags"] = _sort_tags(tags)


def _hash_schema(schema: Mapping[str, Any]) -> str:
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_header_spec() -> dict[str, Any]:
    return {
        "ETag": {
            "description": "Entity tag identifying the cached representation.",
            "schema": {"type": "string"},
        },
        "Last-Modified": {
            "description": "Timestamp of the last modification in RFC 1123 format.",
            "schema": {"type": "string", "format": "date-time"},
        },
        "Cache-Control": {
            "description": "Cache directives for clients and proxies.",
            "schema": {"type": "string"},
        },
        "Vary": {
            "description": "Headers that affect the cached representation.",
            "schema": {"type": "string"},
        },
    }


def _error_responses() -> dict[str, str]:
    return {
        "400": "Validation error",
        "404": "Resource not found",
        "429": "Too many requests",
        "424": "Failed dependency",
        "500": "Internal server error",
        "502": "Bad gateway",
        "503": "Service unavailable",
        "504": "Gateway timeout",
    }


def _apply_error_contract(paths: MutableMapping[str, Any]) -> None:
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for item in paths.values():
        if not isinstance(item, MutableMapping):
            continue
        for operation in item.values():
            if not isinstance(operation, MutableMapping):
                continue
            responses = operation.setdefault("responses", {})
            if isinstance(responses, MutableMapping):
                for status_code, description in _error_responses().items():
                    existing = responses.get(status_code)
                    if existing is None:
                        responses[status_code] = {
                            "description": description,
                            "content": {"application/json": {"schema": error_ref}},
                        }
                        continue
                    if isinstance(existing, MutableMapping):
                        existing.setdefault("description", description)
                        content = existing.setdefault("content", {})
                        if isinstance(content, MutableMapping):
                            content.setdefault("application/json", {"schema": error_ref})


def _apply_cache_headers(paths: MutableMapping[str, Any]) -> None:
    cache_headers = _cache_header_spec()
    for item in paths.values():
        if not isinstance(item, MutableMapping):
            continue
        for method, operation in item.items():
            if method.lower() != "get" or not isinstance(operation, MutableMapping):
                continue
            responses = operation.setdefault("responses", {})
            success = responses.get("200")
            if isinstance(success, MutableMapping):
                headers = success.setdefault("headers", {})
                if isinstance(headers, MutableMapping):
                    for header_name, spec in cache_headers.items():
                        headers.setdefault(header_name, deepcopy(spec))
            not_modified = responses.setdefault(
                "304",
                {
                    "description": "Not Modified",
                    "headers": {},
                },
            )
            if isinstance(not_modified, MutableMapping):
                headers = not_modified.setdefault("headers", {})
                if isinstance(headers, MutableMapping):
                    for header_name in (
                        "ETag",
                        "Last-Modified",
                        "Cache-Control",
                        "Vary",
                    ):
                        headers.setdefault(header_name, deepcopy(cache_headers[header_name]))


def _apply_health_examples(app: FastAPI, paths: MutableMapping[str, Any]) -> None:
    config = getattr(app.state, "openapi_config", None)
    if not isinstance(config, AppConfig):
        return
    health_path = router_registry.compose_prefix(config.api_base_path, "/health")
    ready_path = router_registry.compose_prefix(config.api_base_path, "/ready")
    health_item = paths.get(health_path)
    if isinstance(health_item, MutableMapping):
        operation = health_item.get("get")
        if isinstance(operation, MutableMapping):
            operation.setdefault("summary", "Liveness probe")
            operation.setdefault(
                "description",
                "Returns the service status, version and uptime.",
            )
            responses = operation.setdefault("responses", {})
            responses["200"] = {
                "description": "Liveness status",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/HealthResponse"},
                        "example": {
                            "ok": True,
                            "data": {
                                "status": "up",
                                "version": app.version,
                                "uptime_s": 1.23,
                            },
                            "error": None,
                        },
                    }
                },
            }
    ready_item = paths.get(ready_path)
    if isinstance(ready_item, MutableMapping):
        operation = ready_item.get("get")
        if isinstance(operation, MutableMapping):
            operation.setdefault("summary", "Readiness probe")
            operation.setdefault(
                "description",
                "Checks database connectivity and downstream dependencies.",
            )
            responses = operation.setdefault("responses", {})
            responses["200"] = {
                "description": "All dependencies ready",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ReadySuccessResponse"},
                        "example": {
                            "ok": True,
                            "data": {
                                "db": "up",
                                "deps": {"spotify": "up"},
                                "orchestrator": {
                                    "components": {"scheduler": "up"},
                                    "jobs": {"sync": "idle"},
                                    "enabled_jobs": {"sync": True},
                                },
                            },
                            "error": None,
                        },
                    }
                },
            }
            responses["503"] = {
                "description": "Dependencies unavailable",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        "example": {
                            "ok": False,
                            "error": {
                                "code": "DEPENDENCY_ERROR",
                                "message": "not ready",
                                "meta": {
                                    "db": "down",
                                    "deps": {"spotify": "down"},
                                    "orchestrator": {
                                        "components": {"scheduler": "down"},
                                        "jobs": {"sync": "failed"},
                                        "enabled_jobs": {"sync": False},
                                    },
                                },
                            },
                        },
                    }
                },
            }


def _ensure_feature_snapshot(config: AppConfig) -> AppConfig:
    snapshot = deepcopy(config)
    snapshot.features = replace(config.features)
    return snapshot


def build_openapi_schema(app: FastAPI, *, config: AppConfig) -> dict[str, Any]:
    """Construct a deterministic OpenAPI schema for the given FastAPI app."""

    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )

    config_snapshot = _ensure_feature_snapshot(config)
    server_url = _normalise_server_url(config_snapshot.api_base_path or "/")
    schema["servers"] = [{"url": server_url}]

    components = schema.setdefault("components", {})
    security_scheme_name = "ApiKeyAuth"
    security_scheme = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": (
            "Provide the configured API key via the X-API-Key header. Authorization: "
            "Bearer is also supported."
        ),
    }
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes[security_scheme_name] = security_scheme

    schemas_section = components.setdefault("schemas", {})
    schemas_section.setdefault(
        "ErrorObject",
        {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {
                    "type": "string",
                    "enum": [
                        "VALIDATION_ERROR",
                        "NOT_FOUND",
                        "RATE_LIMITED",
                        "DEPENDENCY_ERROR",
                        "INTERNAL_ERROR",
                    ],
                },
                "message": {"type": "string"},
                "meta": {"type": "object", "additionalProperties": True},
            },
        },
    )
    schemas_section.setdefault(
        "ErrorResponse",
        {
            "type": "object",
            "required": ["ok", "error"],
            "properties": {
                "ok": {"type": "boolean", "const": False},
                "error": {"$ref": "#/components/schemas/ErrorObject"},
            },
        },
    )
    schemas_section.setdefault(
        "HealthData",
        {
            "type": "object",
            "required": ["status", "version", "uptime_s"],
            "properties": {
                "status": {"type": "string", "enum": ["up"]},
                "version": {"type": "string"},
                "uptime_s": {"type": "number"},
            },
        },
    )
    schemas_section.setdefault(
        "HealthResponse",
        {
            "type": "object",
            "required": ["ok", "data", "error"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "data": {"$ref": "#/components/schemas/HealthData"},
                "error": {"type": "null"},
            },
        },
    )
    schemas_section.setdefault(
        "ReadyData",
        {
            "type": "object",
            "required": ["db", "deps", "orchestrator"],
            "properties": {
                "db": {"type": "string"},
                "deps": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "orchestrator": {
                    "type": "object",
                    "required": ["components", "jobs", "enabled_jobs"],
                    "properties": {
                        "components": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "jobs": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "enabled_jobs": {
                            "type": "object",
                            "additionalProperties": {"type": "boolean"},
                        },
                    },
                },
            },
        },
    )
    schemas_section.setdefault(
        "ReadySuccessResponse",
        {
            "type": "object",
            "required": ["ok", "data", "error"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "data": {"$ref": "#/components/schemas/ReadyData"},
                "error": {"type": "null"},
            },
        },
    )

    security_config = config_snapshot.security
    require_auth = security_config.require_auth
    api_keys = security_config.api_keys
    if require_auth and api_keys:
        schema["security"] = [{security_scheme_name: []}]
        paths = schema.setdefault("paths", {})
        for path, methods in paths.items():
            if not isinstance(methods, MutableMapping):
                continue
            if _is_allowlisted_path(path, security_config.allowlist):
                for operation in methods.values():
                    if isinstance(operation, MutableMapping):
                        operation.pop("security", None)
    else:
        schema["security"] = []

    paths = schema.setdefault("paths", {})
    _apply_cache_headers(paths)
    _apply_error_contract(paths)

    artist_collection_path = router_registry.compose_prefix(
        config_snapshot.api_base_path, "/artists"
    )
    artist_watchlist_path = router_registry.compose_prefix(
        config_snapshot.api_base_path, "/artists/watchlist"
    )
    artist_detail_path = router_registry.compose_prefix(
        config_snapshot.api_base_path, "/artists/{artist_key}"
    )
    artist_enqueue_path = router_registry.compose_prefix(
        config_snapshot.api_base_path, "/artists/{artist_key}/enqueue-sync"
    )
    apply_artist_examples(
        schema,
        collection_path=artist_collection_path,
        watchlist_path=artist_watchlist_path,
        detail_path=artist_detail_path,
        enqueue_path=artist_enqueue_path,
    )
    _apply_health_examples(app, paths)

    _ensure_deterministic_structure(schema)
    schema_hash = _hash_schema(schema)
    info = schema.setdefault("info", {})
    info["x-schema-hash"] = schema_hash
    schema["info"] = _sort_dict_recursive(info)
    return schema


def _is_allowlisted_path(path: str, allowlist: tuple[str, ...]) -> bool:
    for prefix in allowlist:
        if not prefix:
            continue
        if prefix == "/" and path == "/":
            return True
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


__all__ = ["build_openapi_schema"]
