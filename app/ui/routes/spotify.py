from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Awaitable
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.spotify import _parse_multipart_file
from app.errors import AppError
from app.logging_events import log_event
from app.ui.context.base import AlertMessage, FormDefinition
from app.ui.context.spotify import (
    build_spotify_account_context,
    build_spotify_artists_context,
    build_spotify_backfill_context,
    build_spotify_free_ingest_context,
    build_spotify_page_context,
    build_spotify_playlist_items_context,
    build_spotify_playlists_context,
    build_spotify_recommendations_context,
    build_spotify_saved_tracks_context,
    build_spotify_status_context,
    build_spotify_top_artists_context,
    build_spotify_top_tracks_context,
    build_spotify_track_detail_context,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _parse_form_body,
    _render_alert_fragment,
    logger,
    templates,
)
from app.ui.services import (
    SpotifyFreeIngestResult,
    SpotifyPlaylistFilters,
    SpotifyPlaylistRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifyUiService,
    get_spotify_ui_service,
)
from app.ui.session import (
    UiSession,
    get_spotify_backfill_job_id,
    get_spotify_free_ingest_job_id,
    require_operator_with_feature,
    require_role,
    set_spotify_backfill_job_id,
    set_spotify_free_ingest_job_id,
)

_SPOTIFY_TIME_RANGES = frozenset({"short_term", "medium_term", "long_term"})
_DEFAULT_TIME_RANGE = "medium_term"

_SAVED_TRACKS_LIMIT_COOKIE = "spotify_saved_tracks_limit"
_SAVED_TRACKS_OFFSET_COOKIE = "spotify_saved_tracks_offset"
_SPOTIFY_BACKFILL_TIMELINE_LIMIT = 10


router = APIRouter()


@dataclass(slots=True)
class RecommendationsFormData:
    values: Mapping[str, str]
    artist_seeds: tuple[str, ...]
    track_seeds: tuple[str, ...]
    genre_seeds: tuple[str, ...]
    errors: Mapping[str, str]
    alerts: tuple[AlertMessage, ...]
    limit: int
    general_error: bool
    action: str
    queue_track_ids: tuple[str, ...]


async def _handle_backfill_action(
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    *,
    action: Callable[[SpotifyUiService, str], Awaitable[Mapping[str, object]]],
    success_message: str,
    event_key: str,
) -> Response:
    values = _parse_form_body(await request.body())
    job_id = values.get("job_id", "")
    if not job_id:
        return _render_alert_fragment(
            request,
            "A backfill job identifier is required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        status_payload = await action(service, job_id)
    except PermissionError as exc:
        logger.warning("spotify.ui.backfill.denied", extra={"error": str(exc)})
        return _render_alert_fragment(
            request,
            "Spotify authentication is required before managing backfill jobs.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except LookupError:
        return _render_alert_fragment(
            request,
            "The requested backfill job could not be found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc) or "Invalid backfill action request.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        logger.warning("spotify.ui.backfill.error", extra={"error": exc.code})
        return _render_alert_fragment(
            request,
            exc.message if exc.message else "Unable to update the backfill job.",
        )
    except Exception:
        logger.exception("spotify.ui.backfill.error")
        return _render_alert_fragment(
            request,
            "Failed to update the backfill job.",
        )

    await set_spotify_backfill_job_id(request, session, job_id)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    snapshot = await service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    alert = AlertMessage(level="success", text=success_message.format(job_id=job_id))
    context = build_spotify_backfill_context(
        request,
        snapshot=snapshot,
        alert=alert,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_backfill.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_key,
        component="ui.router",
        status="success",
        role=session.role,
        job_id=job_id,
        state=status_payload.get("state"),
    )
    return response


def _extract_saved_tracks_pagination(request: Request) -> tuple[int, int]:
    def _coerce(
        raw: str | None,
        default: int,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        try:
            value = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            value = default
        value = max(minimum, value)
        if maximum is not None:
            value = min(value, maximum)
        return value

    default_limit = 25
    default_offset = 0

    header_url = request.headers.get("hx-current-url")
    header_params: dict[str, str] = {}
    if header_url:
        try:
            parsed = urlparse(header_url)
        except ValueError:
            parsed = None
        if parsed is not None:
            header_params = {
                key: values[0] for key, values in parse_qs(parsed.query).items() if values
            }

    def _resolve(key: str, *, fallback: str | None = None) -> str | None:
        value = request.query_params.get(key)
        if value not in (None, ""):
            return value
        value = header_params.get(key)
        if value not in (None, ""):
            return value
        value = request.cookies.get(
            {
                "limit": _SAVED_TRACKS_LIMIT_COOKIE,
                "offset": _SAVED_TRACKS_OFFSET_COOKIE,
            }[key]
        )
        if value not in (None, ""):
            return value
        return fallback

    limit = _coerce(
        _resolve("limit", fallback=str(default_limit)),
        default_limit,
        minimum=1,
        maximum=50,
    )
    offset = _coerce(
        _resolve("offset", fallback=str(default_offset)),
        default_offset,
        minimum=0,
    )
    return limit, offset


def _persist_saved_tracks_pagination(response: Response, *, limit: int, offset: int) -> None:
    response.set_cookie(
        _SAVED_TRACKS_LIMIT_COOKIE,
        str(limit),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/ui/spotify",
    )
    response.set_cookie(
        _SAVED_TRACKS_OFFSET_COOKIE,
        str(offset),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/ui/spotify",
    )


def _extract_time_range(request: Request) -> str:
    value = request.query_params.get("time_range")
    if value in _SPOTIFY_TIME_RANGES:
        return value
    return _DEFAULT_TIME_RANGE


def _split_seed_ids(raw_value: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for entry in re.split(r"[\s,]+", raw_value.strip()):
        candidate = entry.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in seen:
            continue
        cleaned.append(candidate)
        seen.add(lowered)
    return cleaned


def _split_seed_genres(raw_value: str) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    normalised = raw_value.replace("\r", "\n")
    for part in normalised.split("\n"):
        for chunk in part.split(","):
            candidate = chunk.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            entries.append(candidate)
            seen.add(lowered)
    return entries


def _split_ingest_lines(raw_value: str) -> list[str]:
    entries: list[str] = []
    normalised = raw_value.replace("\r", "\n")
    for part in normalised.split("\n"):
        candidate = part.strip()
        if not candidate:
            continue
        entries.append(candidate)
    return entries


def _ensure_imports_feature_enabled(session: UiSession) -> None:
    if not session.features.imports:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )


def _render_recommendations_response(
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    *,
    issued: bool,
    rows: Sequence[SpotifyRecommendationRow] = (),
    seeds: Sequence[SpotifyRecommendationSeed] = (),
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    alerts: Sequence[AlertMessage] | None = None,
    seed_defaults: Mapping[str, str] | None = None,
    show_admin_controls: bool = False,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    limit, offset = _extract_saved_tracks_pagination(request)
    context = build_spotify_recommendations_context(
        request,
        csrf_token=csrf_token,
        rows=rows,
        seeds=seeds,
        limit=limit,
        offset=offset,
        form_values=form_values,
        form_errors=form_errors,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        queue_enabled=session.features.imports,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_recommendations.j2",
        context,
        status_code=status_code,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


def _parse_recommendations_form(
    form: Mapping[str, Sequence[str]],
) -> RecommendationsFormData:
    def _first(name: str) -> str:
        entries = form.get(name, ())
        if entries:
            entry = entries[0]
            return str(entry) if entry is not None else ""
        return ""

    action_raw = _first("action").strip().lower()
    action = action_raw or "submit"

    form_values = {
        "seed_artists": _first("seed_artists").strip(),
        "seed_tracks": _first("seed_tracks").strip(),
        "seed_genres": _first("seed_genres").strip(),
        "limit": _first("limit").strip(),
    }

    queue_candidates: list[str] = []
    for key in ("track_id", "track_ids", "track_id[]"):
        entries = form.get(key, ())
        for entry in entries:
            if isinstance(entry, str):
                queue_candidates.append(entry)

    queue_ids: list[str] = []
    seen_queue: set[str] = set()
    for candidate in queue_candidates:
        for part in re.split(r"[\s,]+", candidate):
            cleaned = part.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen_queue:
                continue
            seen_queue.add(lowered)
            queue_ids.append(cleaned)

    errors: dict[str, str] = {}
    alerts: list[AlertMessage] = []

    limit_value = 20
    limit_raw = form_values["limit"]
    if limit_raw:
        try:
            limit_value = int(limit_raw)
        except (TypeError, ValueError):
            errors["limit"] = "Enter a number between 1 and 100."
    if "limit" not in errors and not 1 <= limit_value <= 100:
        errors["limit"] = "Enter a number between 1 and 100."

    artist_seeds = tuple(_split_seed_ids(form_values["seed_artists"]))
    track_seeds = tuple(_split_seed_ids(form_values["seed_tracks"]))
    genre_seeds = tuple(_split_seed_genres(form_values["seed_genres"]))

    total_seeds = len(artist_seeds) + len(track_seeds) + len(genre_seeds)
    general_error = False
    if action not in {"save_defaults", "load_defaults"}:
        if total_seeds == 0:
            alerts.append(AlertMessage(level="error", text="Provide at least one seed value."))
            general_error = True
        elif total_seeds > 5:
            alerts.append(
                AlertMessage(level="error", text="Specify no more than five seeds in total.")
            )
            general_error = True

    return RecommendationsFormData(
        values=form_values,
        artist_seeds=artist_seeds,
        track_seeds=track_seeds,
        genre_seeds=genre_seeds,
        errors=errors,
        alerts=tuple(alerts),
        limit=limit_value,
        general_error=general_error,
        action=action,
        queue_track_ids=tuple(queue_ids),
    )


def _recommendations_value_error_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    alerts: Sequence[AlertMessage],
    form_values: Mapping[str, str],
    message: str,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    combined_alerts = list(alerts)
    combined_alerts.append(AlertMessage(level="error", text=message))
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="error",
        role=session.role,
        error="validation",
    )
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        alerts=combined_alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _recommendations_app_error_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    alerts: Sequence[AlertMessage],
    error_code: str,
    status_code: int,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="error",
        role=session.role,
        error=error_code,
    )
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status_code,
    )


def _recommendations_unexpected_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    logger.exception("ui.fragment.spotify.recommendations")
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="error",
        role=session.role,
        error="unexpected",
    )
    fallback_alerts = [
        AlertMessage(
            level="error",
            text="Unable to fetch Spotify recommendations.",
        )
    ]
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        alerts=fallback_alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def _execute_recommendations_request(
    *,
    service: SpotifyUiService,
    form_data: RecommendationsFormData,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> tuple[
    tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]] | None,
    Response | None,
]:
    base_args = {
        "request": request,
        "session": session,
        "csrf_manager": csrf_manager,
        "csrf_token": csrf_token,
        "issued": issued,
        "seed_defaults": seed_defaults,
        "show_admin_controls": show_admin_controls,
    }
    form_values = _build_recommendation_form_values(
        artist_seeds=form_data.artist_seeds,
        track_seeds=form_data.track_seeds,
        genre_seeds=form_data.genre_seeds,
        limit_value=form_data.limit,
    )
    try:
        rows, seeds = await service.recommendations(
            seed_tracks=form_data.track_seeds,
            seed_artists=form_data.artist_seeds,
            seed_genres=form_data.genre_seeds,
            limit=form_data.limit,
        )
        return (rows, seeds), None
    except ValueError as exc:
        return None, _recommendations_value_error_response(
            **base_args,
            alerts=form_data.alerts,
            form_values=form_values,
            message=str(exc) or "Unable to fetch Spotify recommendations.",
        )
    except AppError as exc:
        return None, _recommendations_app_error_response(
            **base_args,
            form_values=form_values,
            alerts=[AlertMessage(level="error", text=exc.message)],
            error_code=exc.code,
            status_code=exc.http_status,
        )
    except Exception:
        return None, _recommendations_unexpected_response(
            **base_args,
            form_values=form_values,
        )


def _build_recommendation_form_values(
    *,
    artist_seeds: Sequence[str],
    track_seeds: Sequence[str],
    genre_seeds: Sequence[str],
    limit_value: int,
) -> Mapping[str, str]:
    return {
        "seed_artists": ", ".join(artist_seeds),
        "seed_tracks": ", ".join(track_seeds),
        "seed_genres": ", ".join(genre_seeds),
        "limit": str(limit_value),
    }


def _finalize_recommendations_success(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    rows: Sequence[SpotifyRecommendationRow],
    seeds: Sequence[SpotifyRecommendationSeed],
    form_values: Mapping[str, str],
    alerts: Sequence[AlertMessage] | None,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    response = _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        rows=rows,
        seeds=seeds,
        form_values=form_values,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
    )
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(rows),
    )
    return response


async def _fetch_recommendation_rows(
    *,
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: RecommendationsFormData,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> tuple[
    Mapping[str, str],
    tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]] | None,
    Response | None,
]:
    normalised_values = _build_recommendation_form_values(
        artist_seeds=parsed_form.artist_seeds,
        track_seeds=parsed_form.track_seeds,
        genre_seeds=parsed_form.genre_seeds,
        limit_value=parsed_form.limit,
    )
    result, error_response = await _execute_recommendations_request(
        service=service,
        form_data=parsed_form,
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        form_values=normalised_values,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
    )
    return normalised_values, result, error_response


def _render_recommendations_form(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    seed_defaults: Mapping[str, str],
    show_admin_controls: bool,
    alerts: Sequence[AlertMessage] | None = None,
    form_errors: Mapping[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        form_errors=form_errors,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status_code,
    )


def _ensure_admin(show_admin_controls: bool) -> None:
    if not show_admin_controls:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")


async def _handle_queue_action(
    *,
    service: SpotifyUiService,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: RecommendationsFormData,
    alerts: list[AlertMessage],
    normalised_values: Mapping[str, str],
    current_defaults: Mapping[str, str],
    show_admin_controls: bool,
) -> Response | None:
    if not parsed_form.queue_track_ids:
        alerts.append(
            AlertMessage(level="error", text="Select at least one recommendation to queue.")
        )
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = await service.queue_recommendation_tracks(
            parsed_form.queue_track_ids, imports_enabled=session.features.imports
        )
    except ValueError as exc:
        alerts.append(AlertMessage(level="error", text=str(exc)))
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        alerts.append(AlertMessage(level="error", text=exc.message))
        log_event(
            logger,
            "ui.spotify.recommendations.queue",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.spotify.recommendations.queue")
        alerts.append(AlertMessage(level="error", text="Unable to queue Spotify downloads."))
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    alerts.append(
        AlertMessage(
            level="success",
            text=(
                "Queued "
                f"{result.accepted.tracks:,} Spotify track"
                f"{'s' if result.accepted.tracks != 1 else ''} for download."
            ),
        )
    )
    log_event(
        logger,
        "ui.spotify.recommendations.queue",
        component="ui.router",
        status="success",
        role=session.role,
        count=result.accepted.tracks,
        job_id=result.job_id,
    )
    return None


def _handle_defaults_action(
    *,
    action: str,
    service: SpotifyUiService,
    parsed_form: RecommendationsFormData,
    alerts: list[AlertMessage],
    current_defaults: Mapping[str, str],
    show_admin_controls: bool,
) -> Mapping[str, str]:
    if action == "save_defaults":
        _ensure_admin(show_admin_controls)
        updated = service.save_recommendation_seed_defaults(
            seed_tracks=parsed_form.track_seeds,
            seed_artists=parsed_form.artist_seeds,
            seed_genres=parsed_form.genre_seeds,
        )
        alerts.append(AlertMessage(level="success", text="Default recommendation seeds saved."))
        return dict(updated)
    if action == "load_defaults":
        _ensure_admin(show_admin_controls)
        if not any(value.strip() for value in current_defaults.values()):
            alerts.append(
                AlertMessage(level="info", text="No default recommendation seeds are configured.")
            )
        return current_defaults
    return current_defaults


async def _process_recommendations_submission(
    *,
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: RecommendationsFormData,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    current_defaults = dict(seed_defaults or {})
    alerts = list(parsed_form.alerts)
    form_errors = dict(parsed_form.errors)
    normalised_values = _build_recommendation_form_values(
        artist_seeds=parsed_form.artist_seeds,
        track_seeds=parsed_form.track_seeds,
        genre_seeds=parsed_form.genre_seeds,
        limit_value=parsed_form.limit,
    )

    if form_errors or parsed_form.general_error:
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=parsed_form.values,
            form_errors=form_errors,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if parsed_form.action == "queue":
        queue_response = await _handle_queue_action(
            service=service,
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            parsed_form=parsed_form,
            alerts=alerts,
            normalised_values=normalised_values,
            current_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
        )
        if queue_response is not None:
            return queue_response

    else:
        current_defaults = _handle_defaults_action(
            action=parsed_form.action,
            service=service,
            parsed_form=parsed_form,
            alerts=alerts,
            current_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
        )

    normalised_values, result, error_response = await _fetch_recommendation_rows(
        request=request,
        session=session,
        service=service,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        parsed_form=parsed_form,
        seed_defaults=current_defaults,
        show_admin_controls=show_admin_controls,
    )
    if error_response is not None:
        return error_response

    rows, seeds = result
    return _finalize_recommendations_success(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        rows=rows,
        seeds=seeds,
        form_values=normalised_values,
        alerts=tuple(alerts),
        seed_defaults=current_defaults,
        show_admin_controls=show_admin_controls,
    )


async def _read_recommendations_form(request: Request) -> Mapping[str, Sequence[str]]:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    return {key: list(entries) for key, entries in values.items()}


def _normalize_playlist_filter(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate or None


async def _read_playlist_filter_form(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)

    def _first(name: str) -> str:
        entries = values.get(name)
        if entries:
            return entries[0]
        return ""

    return {
        "owner": _first("owner"),
        "status": _first("status"),
    }


def _render_spotify_playlists_fragment_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    playlists: Sequence[SpotifyPlaylistRow],
    filter_options: SpotifyPlaylistFilters,
    owner_filter: str | None,
    status_filter: str | None,
) -> Response:
    filter_action = request.url_for("spotify_playlists_filter")
    refresh_url = request.url_for("spotify_playlists_refresh")
    table_target = "#spotify-playlists-fragment"
    force_sync_url: str | None = None
    if session.allows("admin"):
        try:
            force_sync_url = request.url_for("spotify_playlists_force_sync")
        except Exception:  # pragma: no cover - defensive guard
            force_sync_url = None

    context = build_spotify_playlists_context(
        request,
        playlists=playlists,
        csrf_token=csrf_token,
        filter_action=filter_action,
        refresh_url=refresh_url,
        table_target=table_target,
        owner_options=filter_options.owners,
        sync_status_options=filter_options.sync_statuses,
        owner_filter=owner_filter,
        status_filter=status_filter,
        force_sync_url=force_sync_url,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_playlists.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/spotify", include_in_schema=False)
async def spotify_page(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/spotify.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/spotify/oauth/start",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_oauth_start(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        authorization_url = service.start_oauth()
    except ValueError as exc:
        logger.warning("spotify.ui.oauth.start.error", extra={"error": str(exc)})
        return _render_alert_fragment(
            request,
            str(exc) or "Spotify OAuth is currently unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    response = RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)
    response.headers.setdefault("HX-Redirect", authorization_url)
    log_event(
        logger,
        "ui.spotify.oauth.start",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return response


@router.post(
    "/spotify/oauth/manual",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_oauth_manual(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    redirect_url = values.get("redirect_url", [""])[0].strip()
    if not redirect_url:
        return _render_alert_fragment(
            request,
            "A redirect URL from Spotify is required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    result = await service.manual_complete(redirect_url=redirect_url)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    context = build_spotify_status_context(
        request,
        status=await service.status(),
        oauth=service.oauth_health(),
        manual_form=manual_form,
        csrf_token=csrf_token,
        manual_result=result,
        manual_redirect_url=redirect_url if not result.ok else None,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_status.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.spotify.oauth.manual",
        component="ui.router",
        status="success" if result.ok else "error",
        role=session.role,
    )
    return response


@router.post(
    "/spotify/free/run",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_free_ingest_run(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    _ensure_imports_feature_enabled(session)

    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    playlist_raw = values.get("playlist_links", [""])[0]
    tracks_raw = values.get("tracks", [""])[0]
    form_values = {"playlist_links": playlist_raw, "tracks": tracks_raw}
    playlist_links = _split_ingest_lines(playlist_raw)
    track_entries = _split_ingest_lines(tracks_raw)

    alerts: list[AlertMessage] = []
    form_errors: dict[str, str] = {}
    result: SpotifyFreeIngestResult | None

    if not playlist_links and not track_entries:
        message = "Provide at least one playlist link or track entry."
        form_errors["playlist_links"] = message
        alerts.append(AlertMessage(level="error", text=message))
        result = None
        service.consume_free_ingest_feedback()
    else:
        awaited_result = await service.free_import(
            playlist_links=playlist_links or None,
            tracks=track_entries or None,
        )
        stored_result, stored_error = service.consume_free_ingest_feedback()
        result = stored_result or awaited_result
        message = stored_error or (result.error if result else None)
        if result and message and not result.ok:
            alerts.append(AlertMessage(level="error", text=message))
        elif result and result.job_id:
            alerts.append(
                AlertMessage(
                    level="success",
                    text=f"Free ingest job {result.job_id} enqueued.",
                )
            )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    stored_job_id = await get_spotify_free_ingest_job_id(request, session)
    if result and result.ok and result.job_id:
        stored_job_id = result.job_id
        await set_spotify_free_ingest_job_id(request, session, result.job_id)

    job_status = await service.free_ingest_job_status(stored_job_id)

    context = build_spotify_free_ingest_context(
        request,
        csrf_token=csrf_token,
        form_values=form_values,
        form_errors=form_errors,
        result=result,
        job_status=job_status,
        alerts=alerts,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_free_ingest.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)

    if result is not None:
        log_event(
            logger,
            "ui.spotify.free_ingest.run",
            component="ui.router",
            status="success" if result.ok else "error",
            role=session.role,
            job_id=result.job_id,
        )
    return response


@router.post(
    "/spotify/free/upload",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_free_ingest_upload(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    _ensure_imports_feature_enabled(session)

    content_type = request.headers.get("content-type") or ""
    body = await request.body()
    try:
        filename, content = _parse_multipart_file(content_type, body)
    except ValueError as exc:
        message = str(exc) or "Select a track list file to upload."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        awaited_result = await service.upload_free_ingest_file(
            filename=filename,
            content=content,
        )
    except ValueError as exc:
        message = str(exc) or "The uploaded file could not be processed."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.spotify.free_ingest.upload_error")
        return _render_alert_fragment(
            request,
            "Failed to process the uploaded file.",
        )

    result, stored_error = service.consume_free_ingest_feedback()
    result = result or awaited_result

    alerts: list[AlertMessage] = []
    form_errors: dict[str, str] = {}
    if result and stored_error and not result.ok:
        form_errors["upload"] = stored_error
        alerts.append(AlertMessage(level="error", text=stored_error))
    elif result and result.error and not result.ok:
        form_errors["upload"] = result.error
        alerts.append(AlertMessage(level="error", text=result.error))
    elif result and result.job_id:
        alerts.append(
            AlertMessage(
                level="success",
                text=f"Free ingest job {result.job_id} enqueued.",
            )
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    stored_job_id = await get_spotify_free_ingest_job_id(request, session)
    if result and result.ok and result.job_id:
        stored_job_id = result.job_id
        await set_spotify_free_ingest_job_id(request, session, result.job_id)

    job_status = await service.free_ingest_job_status(stored_job_id)

    context = build_spotify_free_ingest_context(
        request,
        csrf_token=csrf_token,
        form_values={"playlist_links": "", "tracks": ""},
        form_errors=form_errors,
        result=result,
        job_status=job_status,
        alerts=alerts,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_free_ingest.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)

    if result is not None:
        log_event(
            logger,
            "ui.spotify.free_ingest.upload",
            component="ui.router",
            status="success" if result.ok else "error",
            role=session.role,
            job_id=result.job_id,
        )
    return response


@router.post(
    "/spotify/backfill/run",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_run(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    max_items_raw = values.get("max_items", [""])[0].strip()
    expand_raw = values.get("expand_playlists", [])
    expand_playlists = any(value.strip() not in {"", "0", "false", "False"} for value in expand_raw)
    include_raw = values.get("include_cached_results", [])
    if not include_raw:
        include_cached_results = True
    else:
        include_cached_results = any(
            value.strip() not in {"", "0", "false", "False"} for value in include_raw
        )
    max_items: int | None
    if max_items_raw:
        try:
            max_items = int(max_items_raw)
            if max_items < 1:
                raise ValueError
        except ValueError:
            return _render_alert_fragment(
                request,
                "Max items must be a positive integer.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    else:
        max_items = None

    try:
        job_id = await service.run_backfill(
            max_items=max_items,
            expand_playlists=expand_playlists,
            include_cached_results=include_cached_results,
        )
    except PermissionError as exc:
        logger.warning("spotify.ui.backfill.denied", extra={"error": str(exc)})
        return _render_alert_fragment(
            request,
            "Spotify authentication is required before running backfill.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except Exception:
        logger.exception("spotify.ui.backfill.error")
        return _render_alert_fragment(
            request,
            "Failed to enqueue the backfill job.",
        )

    await set_spotify_backfill_job_id(request, session, job_id)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    status_payload = await service.backfill_status(job_id)
    snapshot = await service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    alert = AlertMessage(level="success", text=f"Backfill job {job_id} enqueued.")
    context = build_spotify_backfill_context(
        request,
        snapshot=snapshot,
        alert=alert,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_backfill.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.spotify.backfill.run",
        component="ui.router",
        status="success",
        role=session.role,
        job_id=job_id,
    )
    return response


@router.post(
    "/spotify/backfill/pause",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_pause(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return await _handle_backfill_action(
        request,
        session,
        service,
        action=lambda svc, job_id: svc.pause_backfill(job_id),
        success_message="Backfill job {job_id} paused.",
        event_key="ui.spotify.backfill.pause",
    )


@router.post(
    "/spotify/backfill/resume",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_resume(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return await _handle_backfill_action(
        request,
        session,
        service,
        action=lambda svc, job_id: svc.resume_backfill(job_id),
        success_message="Backfill job {job_id} resumed.",
        event_key="ui.spotify.backfill.resume",
    )


@router.post(
    "/spotify/backfill/cancel",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_cancel(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return await _handle_backfill_action(
        request,
        session,
        service,
        action=lambda svc, job_id: svc.cancel_backfill(job_id),
        success_message="Backfill job {job_id} cancelled.",
        event_key="ui.spotify.backfill.cancel",
    )


@router.get(
    "/spotify/free",
    include_in_schema=False,
    name="spotify_free_ingest_fragment",
)
async def spotify_free_ingest_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    _ensure_imports_feature_enabled(session)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    job_id = await get_spotify_free_ingest_job_id(request, session)
    job_status = await service.free_ingest_job_status(job_id)
    context = build_spotify_free_ingest_context(
        request,
        csrf_token=csrf_token,
        job_status=job_status,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_free_ingest.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/spotify/account", include_in_schema=False, name="spotify_account_fragment")
async def spotify_account_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        summary = await service.account()
    except Exception:
        logger.exception("ui.fragment.spotify.account")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify account details.",
        )

    try:
        refresh_action = request.url_for("spotify_account_refresh")
    except Exception:  # pragma: no cover - fallback for tests
        refresh_action = "/ui/spotify/account/refresh"
    show_reset = session.allows("admin")
    reset_action: str | None
    if show_reset:
        try:
            reset_action = request.url_for("spotify_account_reset_scopes")
        except Exception:  # pragma: no cover - fallback for tests
            reset_action = "/ui/spotify/account/reset-scopes"
    else:
        reset_action = None

    context = build_spotify_account_context(
        request,
        account=summary,
        csrf_token=csrf_token,
        refresh_action=refresh_action,
        show_refresh=True,
        show_reset=show_reset,
        reset_action=reset_action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_account.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.account",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fields"]),
    )
    return response


@router.post(
    "/spotify/account/refresh",
    include_in_schema=False,
    name="spotify_account_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_account_refresh(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        summary = await service.refresh_account()
    except Exception:
        logger.exception("ui.fragment.spotify.account.refresh")
        return _render_alert_fragment(
            request,
            "Unable to refresh Spotify account details.",
        )

    try:
        refresh_action = request.url_for("spotify_account_refresh")
    except Exception:  # pragma: no cover - fallback for tests
        refresh_action = "/ui/spotify/account/refresh"
    show_reset = session.allows("admin")
    reset_action: str | None
    if show_reset:
        try:
            reset_action = request.url_for("spotify_account_reset_scopes")
        except Exception:  # pragma: no cover - fallback for tests
            reset_action = "/ui/spotify/account/reset-scopes"
    else:
        reset_action = None

    context = build_spotify_account_context(
        request,
        account=summary,
        csrf_token=csrf_token,
        refresh_action=refresh_action,
        show_refresh=True,
        show_reset=show_reset,
        reset_action=reset_action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_account.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.account.refresh",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fields"]),
    )
    return response


@router.post(
    "/spotify/account/reset-scopes",
    include_in_schema=False,
    name="spotify_account_reset_scopes",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_account_reset_scopes(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    if not session.features.spotify:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        summary = await service.reset_scopes()
    except Exception:
        logger.exception("ui.fragment.spotify.account.reset_scopes")
        return _render_alert_fragment(
            request,
            "Unable to reset Spotify scopes.",
        )

    try:
        refresh_action = request.url_for("spotify_account_refresh")
    except Exception:  # pragma: no cover - fallback for tests
        refresh_action = "/ui/spotify/account/refresh"
    try:
        reset_action = request.url_for("spotify_account_reset_scopes")
    except Exception:  # pragma: no cover - fallback for tests
        reset_action = "/ui/spotify/account/reset-scopes"

    context = build_spotify_account_context(
        request,
        account=summary,
        csrf_token=csrf_token,
        refresh_action=refresh_action,
        show_refresh=True,
        show_reset=True,
        reset_action=reset_action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_account.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.account.reset_scopes",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fields"]),
    )
    return response


@router.get("/spotify/top/tracks", include_in_schema=False, name="spotify_top_tracks_fragment")
async def spotify_top_tracks_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    time_range = _extract_time_range(request)
    try:
        tracks = await service.top_tracks(time_range=time_range)
    except Exception:
        logger.exception("ui.fragment.spotify.top_tracks")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify top tracks.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    limit, offset = _extract_saved_tracks_pagination(request)
    context = build_spotify_top_tracks_context(
        request,
        tracks=tracks,
        csrf_token=csrf_token,
        limit=limit,
        offset=offset,
        time_range=time_range,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_top_tracks.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.top_tracks",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.get("/spotify/top/artists", include_in_schema=False, name="spotify_top_artists_fragment")
async def spotify_top_artists_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    time_range = _extract_time_range(request)
    try:
        artists = await service.top_artists(time_range=time_range)
    except Exception:
        logger.exception("ui.fragment.spotify.top_artists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify top artists.",
        )

    context = build_spotify_top_artists_context(
        request,
        artists=artists,
        time_range=time_range,
    )
    log_event(
        logger,
        "ui.fragment.spotify.top_artists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_top_artists.j2",
        context,
    )


@router.get("/spotify/backfill", include_in_schema=False, name="spotify_backfill_fragment")
async def spotify_backfill_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    job_id = await get_spotify_backfill_job_id(request, session)
    status_payload = await service.backfill_status(job_id)
    snapshot = await service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    timeline = await service.backfill_timeline(limit=_SPOTIFY_BACKFILL_TIMELINE_LIMIT)
    context = build_spotify_backfill_context(request, snapshot=snapshot, timeline=timeline)
    response = templates.TemplateResponse(
        request,
        "partials/spotify_backfill.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/spotify/artists", include_in_schema=False, name="spotify_artists_fragment")
async def spotify_artists_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        artists = await service.list_followed_artists()
    except Exception:
        logger.exception("ui.fragment.spotify.artists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify artists.",
        )
    context = build_spotify_artists_context(request, artists=artists)
    log_event(
        logger,
        "ui.fragment.spotify.artists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_artists.j2",
        context,
    )


@router.get("/spotify/playlists", include_in_schema=False, name="spotify_playlists_fragment")
async def spotify_playlists_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    owner_filter = _normalize_playlist_filter(request.query_params.get("owner"))
    status_filter = _normalize_playlist_filter(request.query_params.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        filter_options = await service.playlist_filters()
        playlists = await service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.playlists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.fragment.spotify.playlists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.post(
    "/spotify/playlists/filter",
    include_in_schema=False,
    name="spotify_playlists_filter",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlists_filter(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    form = await _read_playlist_filter_form(request)
    owner_filter = _normalize_playlist_filter(form.get("owner"))
    status_filter = _normalize_playlist_filter(form.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        filter_options = await service.playlist_filters()
        playlists = await service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.playlists.filter")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.fragment.spotify.playlists.filter",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.post(
    "/spotify/playlists/refresh",
    include_in_schema=False,
    name="spotify_playlists_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlists_refresh(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    form = await _read_playlist_filter_form(request)
    owner_filter = _normalize_playlist_filter(form.get("owner"))
    status_filter = _normalize_playlist_filter(form.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        await service.refresh_playlists()
        filter_options = await service.playlist_filters()
        playlists = await service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.spotify.playlists.refresh")
        return _render_alert_fragment(
            request,
            "Unable to refresh Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.spotify.playlists.refresh",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.post(
    "/spotify/playlists/force-sync",
    include_in_schema=False,
    name="spotify_playlists_force_sync",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlists_force_sync(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    if not session.features.spotify:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    form = await _read_playlist_filter_form(request)
    owner_filter = _normalize_playlist_filter(form.get("owner"))
    status_filter = _normalize_playlist_filter(form.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        await service.force_sync_playlists()
        filter_options = await service.playlist_filters()
        playlists = await service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.spotify.playlists.force_sync")
        return _render_alert_fragment(
            request,
            "Unable to force sync Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.spotify.playlists.force_sync",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.get(
    "/spotify/playlists/{playlist_id}/tracks",
    include_in_schema=False,
    name="spotify_playlist_items_fragment",
)
async def spotify_playlist_items_fragment(
    request: Request,
    playlist_id: str,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    playlist_name: str | None = Query(None, alias="name"),
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        rows, total, page_limit, page_offset = await service.playlist_items(
            playlist_id, limit=limit, offset=offset
        )
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.playlist_items")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlist tracks.",
        )

    context = build_spotify_playlist_items_context(
        request,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        rows=rows,
        total_count=total,
        limit=page_limit,
        offset=page_offset,
    )
    log_event(
        logger,
        "ui.fragment.spotify.playlist_items",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_playlist_items.j2",
        context,
    )


@router.get(
    "/spotify/recommendations",
    include_in_schema=False,
    name="spotify_recommendations_fragment",
)
async def spotify_recommendations_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    seed_defaults = service.get_recommendation_seed_defaults()
    response = _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        seed_defaults=seed_defaults,
        show_admin_controls=session.allows("admin"),
    )
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="success",
        role=session.role,
        count=0,
    )
    return response


@router.post(
    "/spotify/recommendations",
    include_in_schema=False,
    name="spotify_recommendations_submit",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_recommendations_submit(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_form = await _read_recommendations_form(request)
    form = dict(raw_form)

    def _first_action(values: Mapping[str, Sequence[str]]) -> str:
        entries = values.get("action", ())
        if entries:
            candidate = entries[0]
            return str(candidate or "").strip().lower()
        return ""

    action = _first_action(form)
    if action == "queue":
        _ensure_imports_feature_enabled(session)
    show_admin_controls = session.allows("admin")
    seed_defaults = service.get_recommendation_seed_defaults()
    if action == "load_defaults" and show_admin_controls:
        form = dict(form)
        for key in ("seed_artists", "seed_tracks", "seed_genres"):
            form[key] = [seed_defaults.get(key, "")]

    parsed_form = _parse_recommendations_form(form)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    return await _process_recommendations_submission(
        request=request,
        session=session,
        service=service,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        parsed_form=parsed_form,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
    )


@router.get("/spotify/saved", include_in_schema=False, name="spotify_saved_tracks_fragment")
async def spotify_saved_tracks_fragment(
    request: Request,
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0),
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        rows, total = await service.list_saved_tracks(limit=limit, offset=offset)
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.saved")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify saved tracks.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_saved_tracks_context(
        request,
        rows=rows,
        total_count=total,
        limit=limit,
        offset=offset,
        csrf_token=csrf_token,
        queue_enabled=session.features.imports,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_saved_tracks.j2",
        context,
    )
    _persist_saved_tracks_pagination(response, limit=limit, offset=offset)
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.saved",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.api_route(
    "/spotify/saved/{action}",
    methods=["POST", "DELETE"],
    include_in_schema=False,
    name="spotify_saved_tracks_action",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_saved_tracks_action(
    request: Request,
    action: str,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    action_key = action.strip().lower()
    if action_key not in {"save", "remove", "queue"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported action.")

    if action_key == "queue":
        _ensure_imports_feature_enabled(session)

    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)

    def _first(key: str) -> str | None:
        entries = values.get(key)
        if not entries:
            query_entries = request.query_params.getlist(key)  # type: ignore[attr-defined]
        else:
            query_entries = []
        source = entries or query_entries
        if not source:
            return None
        return source[0]

    def _coerce_int(
        raw: str | None, default: int, *, minimum: int, maximum: int | None = None
    ) -> int:
        try:
            value = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            value = default
        if maximum is None:
            return max(minimum, value)
        return max(minimum, min(value, maximum))

    default_limit, default_offset = _extract_saved_tracks_pagination(request)
    limit = _coerce_int(_first("limit"), default_limit, minimum=1, maximum=50)
    offset = _coerce_int(_first("offset"), default_offset, minimum=0)

    track_values: list[str] = []
    for key in ("track_id", "track_ids", "track_id[]"):
        track_values.extend(values.get(key, []))
    if not track_values:
        query_values = []
        for key in ("track_id", "track_ids", "track_id[]"):
            query_values.extend(request.query_params.getlist(key))
        track_values.extend(query_values)

    extracted_ids: list[str] = []
    for candidate in track_values:
        if not isinstance(candidate, str):
            continue
        parts = re.split(r"[\s,]+", candidate)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                extracted_ids.append(cleaned)

    try:
        if action_key == "save":
            affected = await service.save_tracks(extracted_ids)
            event_name = "ui.spotify.saved.save"
            failure_message = "Unable to save Spotify tracks."
        elif action_key == "remove":
            affected = await service.remove_saved_tracks(extracted_ids)
            event_name = "ui.spotify.saved.remove"
            failure_message = "Unable to remove Spotify tracks."
        else:
            result = await service.queue_saved_tracks(
                extracted_ids, imports_enabled=session.features.imports
            )
            affected = int(result.accepted.tracks)
            event_name = "ui.spotify.saved.queue"
            failure_message = "Unable to queue Spotify downloads."
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.spotify.saved.action",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.spotify.saved.action")
        return _render_alert_fragment(
            request,
            failure_message,
        )

    rows, total = await service.list_saved_tracks(limit=limit, offset=offset)
    if total and offset >= total:
        offset = max(total - (total % limit or limit), 0)
        rows, total = await service.list_saved_tracks(limit=limit, offset=offset)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_saved_tracks_context(
        request,
        rows=rows,
        total_count=total,
        limit=limit,
        offset=offset,
        csrf_token=csrf_token,
        queue_enabled=session.features.imports,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_saved_tracks.j2",
        context,
    )
    _persist_saved_tracks_pagination(response, limit=limit, offset=offset)
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        count=affected,
    )
    return response


@router.get(
    "/spotify/tracks/{track_id}",
    include_in_schema=False,
    name="spotify_track_detail",
)
async def spotify_track_detail_modal(
    request: Request,
    track_id: str,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        detail = await service.track_detail(track_id)
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.track_detail")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify track details.",
        )

    context = build_spotify_track_detail_context(request, track=detail)
    response = templates.TemplateResponse(
        request,
        "partials/spotify_track_detail.j2",
        context,
    )
    log_event(
        logger,
        "ui.fragment.spotify.track_detail",
        component="ui.router",
        status="success",
        role=session.role,
        count=1,
    )
    return response


@router.get("/spotify/status", include_in_schema=False, name="spotify_status_fragment")
async def spotify_status_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    context = build_spotify_status_context(
        request,
        status=await service.status(),
        oauth=service.oauth_health(),
        manual_form=manual_form,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_status.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.status",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return response


__all__ = ["router"]
