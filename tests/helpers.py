"""Test utilities for generating API paths with the configured base prefix."""

from __future__ import annotations

from app.dependencies import get_app_config


def api_path(path: str = "") -> str:
    """Return an absolute API path honouring the configured base prefix."""

    base_path = get_app_config().api_base_path or ""
    normalized_path = path.strip()
    if normalized_path and not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    if not normalized_path:
        normalized_path = "/"

    if not base_path or base_path == "/":
        return normalized_path

    base = base_path.rstrip("/") or "/"
    if normalized_path == "/":
        return f"{base}/" if base != "/" else "/"
    if normalized_path.startswith(base):
        return normalized_path
    return f"{base}{normalized_path}"
