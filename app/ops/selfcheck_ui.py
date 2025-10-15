"""Readiness probes for UI templates and static assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

UI_ROOT = Path(__file__).resolve().parent.parent / "ui"

REQUIRED_PAGE_TEMPLATES: tuple[str, ...] = (
    "pages/dashboard.j2",
    "pages/login.j2",
)

REQUIRED_LAYOUT_TEMPLATES: tuple[str, ...] = ("layouts/base.j2",)

REQUIRED_PARTIAL_TEMPLATES: tuple[str, ...] = (
    "partials/_strings.j2",
    "partials/activity_table.j2",
    "partials/alerts.j2",
    "partials/alerts_fragment.j2",
    "partials/downloads_table.j2",
    "partials/forms.j2",
    "partials/jobs_fragment.j2",
    "partials/modals.j2",
    "partials/nav.j2",
    "partials/search_results.j2",
    "partials/status_badges.j2",
    "partials/tables.j2",
    "partials/watchlist_table.j2",
)

REQUIRED_TEMPLATE_FILES: tuple[str, ...] = (
    *REQUIRED_LAYOUT_TEMPLATES,
    *REQUIRED_PAGE_TEMPLATES,
    *REQUIRED_PARTIAL_TEMPLATES,
)

REQUIRED_STATIC_ASSETS: tuple[str, ...] = (
    "css/app.css",
    "js/htmx.min.js",
    "icons.svg",
)


def _probe_required_files(
    root: Path,
    required: Sequence[str],
    *,
    require_non_empty: bool = True,
) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    root_exists = root.exists()

    for relative in required:
        file_path = root / relative
        exists = root_exists and file_path.is_file()
        size: int | None = None
        if exists:
            try:
                size = file_path.stat().st_size
            except OSError:
                size = None

        non_empty = bool(size) if size is not None else False
        entry: dict[str, Any] = {
            "path": str(file_path),
            "exists": exists,
            "size": size,
            "non_empty": non_empty,
        }
        entries[relative] = entry

        if not exists or (require_non_empty and not non_empty):
            missing.append(relative)

    return {
        "root": str(root),
        "root_exists": root_exists,
        "required": list(required),
        "files": entries,
        "missing": missing,
    }


def probe_ui_artifacts(base_path: Path | None = None) -> tuple[bool, dict[str, Any]]:
    """Validate that critical UI templates and static assets are present."""

    root = base_path or UI_ROOT
    templates_root = root / "templates"
    static_root = root / "static"

    templates = _probe_required_files(templates_root, REQUIRED_TEMPLATE_FILES)
    static = _probe_required_files(static_root, REQUIRED_STATIC_ASSETS)

    ok = not templates["missing"] and not static["missing"]
    status = "ok" if ok else "fail"
    details: dict[str, Any] = {
        "status": status,
        "root": str(root),
        "templates": templates,
        "static": static,
    }

    return ok, details


__all__ = [
    "REQUIRED_TEMPLATE_FILES",
    "REQUIRED_STATIC_ASSETS",
    "probe_ui_artifacts",
]
