"""Readiness probes for UI templates and static assets."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

UI_ROOT = Path(__file__).resolve().parent.parent / "ui"

REQUIRED_PAGE_TEMPLATES: tuple[str, ...] = (
    "pages/activity.j2",
    "pages/admin.j2",
    "pages/dashboard.j2",
    "pages/downloads.j2",
    "pages/jobs.j2",
    "pages/login.j2",
    "pages/operations.j2",
    "pages/search.j2",
    "pages/settings.j2",
    "pages/soulseek.j2",
    "pages/spotify.j2",
    "pages/system.j2",
    "pages/watchlist.j2",
)

REQUIRED_LAYOUT_TEMPLATES: tuple[str, ...] = ("layouts/base.j2",)

REQUIRED_PARTIAL_TEMPLATES: tuple[str, ...] = (
    "partials/_strings.j2",
    "partials/activity_table.j2",
    "partials/alerts.j2",
    "partials/alerts_fragment.j2",
    "partials/async_error.j2",
    "partials/downloads_table.j2",
    "partials/forms.j2",
    "partials/jobs_fragment.j2",
    "partials/modals.j2",
    "partials/nav.j2",
    "partials/search_results.j2",
    "partials/settings_artist_preferences.j2",
    "partials/settings_form.j2",
    "partials/settings_history.j2",
    "partials/soulseek_config.j2",
    "partials/soulseek_discography_jobs.j2",
    "partials/soulseek_discography_modal.j2",
    "partials/soulseek_download_artwork.j2",
    "partials/soulseek_download_lyrics.j2",
    "partials/soulseek_download_metadata.j2",
    "partials/soulseek_status.j2",
    "partials/soulseek_uploads.j2",
    "partials/soulseek_user_directory.j2",
    "partials/soulseek_user_info.j2",
    "partials/spotify_account.j2",
    "partials/spotify_artists.j2",
    "partials/spotify_backfill.j2",
    "partials/spotify_free_ingest.j2",
    "partials/spotify_playlist_items.j2",
    "partials/spotify_playlists.j2",
    "partials/spotify_recommendations.j2",
    "partials/spotify_saved_tracks.j2",
    "partials/spotify_status.j2",
    "partials/spotify_top_artists.j2",
    "partials/spotify_top_tracks.j2",
    "partials/spotify_track_detail.j2",
    "partials/status_badges.j2",
    "partials/system_integrations.j2",
    "partials/system_liveness.j2",
    "partials/system_readiness.j2",
    "partials/system_secret_card.j2",
    "partials/system_services.j2",
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
    "icons.svg",
    "js/htmx-error-handler.js",
    "js/htmx.min.js",
    "js/polling-controller.js",
    "js/ui-bootstrap.js",
)


def _probe_required_files(
    root: Path,
    required: Sequence[str],
    *,
    require_non_empty: bool = True,
) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    unreadable: list[str] = []
    empty: list[str] = []
    root_exists = root.exists()

    for relative in required:
        file_path = root / relative
        exists = root_exists and file_path.is_file()
        size: int | None = None
        readable = False
        error: str | None = None

        if exists:
            try:
                stat_result = file_path.stat()
                size = stat_result.st_size
            except OSError as exc:
                error = str(exc)
            else:
                try:
                    with file_path.open("rb") as handle:
                        handle.read(1)
                    readable = True
                except OSError as exc:
                    error = str(exc)

        non_empty = bool(size) if size is not None else False
        entry: dict[str, Any] = {
            "path": str(file_path),
            "exists": exists,
            "size": size,
            "non_empty": non_empty,
            "readable": readable,
            "error": error,
        }
        entries[relative] = entry

        if not exists:
            missing.append(relative)
        elif not readable:
            unreadable.append(relative)
        elif require_non_empty and not non_empty:
            empty.append(relative)

    return {
        "root": str(root),
        "root_exists": root_exists,
        "required": list(required),
        "files": entries,
        "missing": missing,
        "unreadable": unreadable,
        "empty": empty,
    }


def probe_ui_artifacts(base_path: Path | None = None) -> tuple[bool, dict[str, Any]]:
    """Validate that critical UI templates and static assets are present."""

    root = base_path or UI_ROOT
    templates_root = root / "templates"
    static_root = root / "static"

    templates = _probe_required_files(templates_root, REQUIRED_TEMPLATE_FILES)
    static = _probe_required_files(static_root, REQUIRED_STATIC_ASSETS)

    template_failures = templates["missing"] or templates["unreadable"] or templates["empty"]
    static_failures = static["missing"] or static["unreadable"] or static["empty"]
    ok = not template_failures and not static_failures
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
