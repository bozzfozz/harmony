"""Utilities for evaluating service credential health."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting


def _normalize_service_name(service: str) -> str:
    """Return the canonical representation for a service name."""

    normalized = service.strip().lower()
    if not normalized:
        raise KeyError("Unknown service ''")
    return normalized


@dataclass(frozen=True)
class ServiceDefinition:
    """Describe the required configuration for a service."""

    name: str
    required_keys: tuple[str, ...]
    optional_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceHealth:
    """Represents the outcome of a health evaluation."""

    service: str
    status: str
    missing: tuple[str, ...]
    optional_missing: tuple[str, ...]


_SERVICE_DEFINITIONS: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        name="spotify",
        required_keys=(
            "SPOTIFY_CLIENT_ID",
            "SPOTIFY_CLIENT_SECRET",
            "SPOTIFY_REDIRECT_URI",
        ),
    ),
    ServiceDefinition(
        name="soulseek",
        required_keys=("SLSKD_URL",),
        optional_keys=("SLSKD_API_KEY",),
    ),
)


def _definition_for(service: str) -> ServiceDefinition:
    normalized = _normalize_service_name(service)
    for definition in _SERVICE_DEFINITIONS:
        if definition.name == normalized:
            return definition
    raise KeyError(f"Unknown service '{service}'")


def _normalized_env_value(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _fetch_settings(
    session: Session, keys: Sequence[str], env: Mapping[str, str]
) -> Mapping[str, str | None]:
    if not keys:
        return {}
    records = session.execute(select(Setting).where(Setting.key.in_(keys))).scalars().all()
    stored = {record.key: record.value for record in records}

    resolved: dict[str, str | None] = {}
    for key in keys:
        value = stored.get(key)
        if value is not None and value.strip():
            resolved[key] = value
            continue
        env_value = _normalized_env_value(env, key)
        if env_value is not None:
            resolved[key] = env_value
            continue
        resolved[key] = value

    return resolved


def _is_missing(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip() == ""


def evaluate_service_health(
    session: Session,
    service: str,
    *,
    env: Mapping[str, str] | None = None,
) -> ServiceHealth:
    """Evaluate credential health for the given service."""

    definition = _definition_for(service)
    keys: list[str] = list(definition.required_keys + definition.optional_keys)
    settings = _fetch_settings(session, keys, env or os.environ)

    def _resolve(key: str) -> str | None:
        return settings.get(key)

    missing_required = tuple(key for key in definition.required_keys if _is_missing(_resolve(key)))
    missing_optional = tuple(key for key in definition.optional_keys if _is_missing(_resolve(key)))

    status = "ok" if not missing_required else "fail"
    return ServiceHealth(
        service=definition.name,
        status=status,
        missing=missing_required,
        optional_missing=missing_optional,
    )


def evaluate_all_service_health(
    session: Session, *, env: Mapping[str, str] | None = None
) -> Mapping[str, ServiceHealth]:
    """Return credential health for all configured services."""

    return {
        definition.name: evaluate_service_health(session, definition.name, env=env)
        for definition in _SERVICE_DEFINITIONS
    }


def collect_missing_credentials(
    session: Session,
    services: Iterable[str],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Return missing required credentials for the given services."""

    missing: dict[str, tuple[str, ...]] = {}
    for service in services:
        health = evaluate_service_health(session, service, env=env)
        if health.missing:
            missing[health.service] = tuple(health.missing)
    return missing


__all__ = [
    "ServiceDefinition",
    "ServiceHealth",
    "evaluate_service_health",
    "evaluate_all_service_health",
    "collect_missing_credentials",
]
