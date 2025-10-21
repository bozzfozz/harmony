from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import Request

from app.api.search import DEFAULT_SOURCES
from app.ui.session import UiSession

from .base import (
    AsyncFragment,
    CheckboxGroup,
    CheckboxOption,
    FormDefinition,
    FormField,
    LayoutContext,
    MetaTag,
    PaginationContext,
    TableCell,
    TableCellForm,
    TableDefinition,
    TableFragment,
    TableRow,
    _build_primary_navigation,
    _safe_url_for,
)

if TYPE_CHECKING:
    from app.ui.services import SearchResultsPage

_SEARCH_SOURCE_LABELS: dict[str, str] = {
    "spotify": "search.sources.spotify",
    "soulseek": "search.sources.soulseek",
}


def _build_search_form(default_sources: Sequence[str]) -> FormDefinition:
    default_source_set = {source for source in default_sources}
    ordered_sources = list(_SEARCH_SOURCE_LABELS.keys())
    for source in DEFAULT_SOURCES:
        if source not in ordered_sources:
            ordered_sources.append(source)

    checkbox_options: list[CheckboxOption] = []
    for source in ordered_sources:
        label_key = _SEARCH_SOURCE_LABELS.get(source, f"search.sources.{source}")
        checkbox_options.append(
            CheckboxOption(
                value=source,
                label_key=label_key,
                checked=source in default_source_set,
                test_id=f"search-source-{source}",
            )
        )

    sources_group = CheckboxGroup(
        name="sources",
        legend_key="search.sources.legend",
        description_key="search.sources.description",
        options=tuple(checkbox_options),
    )

    return FormDefinition(
        identifier="search-form",
        method="post",
        action="/ui/search/results",
        submit_label_key="search.submit",
        fields=(
            FormField(
                name="query",
                input_type="search",
                label_key="search.query",
                autocomplete="off",
                required=True,
            ),
            FormField(
                name="limit",
                input_type="number",
                label_key="search.limit",
            ),
        ),
        checkbox_groups=(sources_group,),
    )


def build_search_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="search",
        role=session.role,
        navigation=_build_primary_navigation(session, active="soulseek"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    search_form = _build_search_form(DEFAULT_SOURCES)

    results_url = _safe_url_for(request, "search_results", "/ui/search/results")
    results_fragment = AsyncFragment(
        identifier="hx-search-results",
        url=results_url,
        target="#hx-search-results",
        swap="innerHTML",
        loading_key="search.results",
    )

    queue_fragment: AsyncFragment | None = None
    if session.features.dlq:
        queue_url = _safe_url_for(request, "downloads_table", "/ui/downloads/table")
        queue_fragment = AsyncFragment(
            identifier="hx-search-queue",
            url=f"{queue_url}?limit=20",
            target="#hx-search-queue",
            poll_interval_seconds=30,
            swap="innerHTML",
            loading_key="search.queue",
            load_event="revealed",
        )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "search_form": search_form,
        "results_fragment": results_fragment,
        "queue_fragment": queue_fragment,
    }


def build_search_results_context(
    request: Request,
    *,
    page: "SearchResultsPage",
    query: str,
    sources: Sequence[str],
    csrf_token: str,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    try:
        action_url = request.url_for("search_download_action")
    except Exception:  # pragma: no cover - fallback for tests
        action_url = "/ui/search/download"
    feedback_target = "#hx-search-feedback"
    for item in page.items:
        score = f"{item.score * 100:.0f}%"
        bitrate = f"{item.bitrate} kbps" if item.bitrate else ""
        if item.download:
            serialised_files = json.dumps(
                [dict(file) for file in item.download.files],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            hidden_fields = {
                "csrftoken": csrf_token,
                "identifier": item.identifier,
                "username": item.download.username,
                "files": serialised_files,
            }
            form = TableCellForm(
                action=action_url,
                method="post",
                submit_label_key="search.action.queue",
                hidden_fields=hidden_fields,
                hx_target=feedback_target,
            )
            action_cell = TableCell(form=form, test_id=f"queue-{item.identifier}")
        else:
            action_cell = TableCell(text_key="search.action.unavailable")
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=item.title),
                    TableCell(text=item.artist or ""),
                    TableCell(text=item.source),
                    TableCell(text=score),
                    TableCell(text=bitrate),
                    action_cell,
                )
            )
        )

    table = TableDefinition(
        identifier="search-results-table",
        column_keys=(
            "search.title",
            "search.artist",
            "search.source",
            "search.score",
            "search.bitrate",
            "search.actions",
        ),
        rows=tuple(rows),
        caption_key="search.results.caption",
    )

    try:
        base_url = request.url_for("search_results")
    except Exception:  # pragma: no cover - fallback for tests
        base_url = "/ui/search/results"

    resolved_sources: tuple[str, ...]
    if sources:
        resolved_sources = tuple(dict.fromkeys(sources))
    else:
        resolved_sources = DEFAULT_SOURCES

    def _make_query(offset: int | None) -> str | None:
        if offset is None or offset < 0:
            return None
        query_params: list[tuple[str, str]] = [
            ("query", query),
            ("limit", str(page.limit)),
            ("offset", str(offset)),
        ]
        for source in resolved_sources:
            query_params.append(("sources", source))
        return f"{base_url}?{urlencode(query_params)}"

    has_previous = page.offset > 0
    previous_offset = page.offset - page.limit if has_previous else None
    next_offset = page.offset + page.limit
    has_next = next_offset < page.total

    pagination: PaginationContext | None = None
    if has_previous or has_next:
        pagination = PaginationContext(
            label_key="search",
            target="#hx-search-results",
            previous_url=_make_query(previous_offset) if has_previous else None,
            next_url=_make_query(next_offset) if has_next else None,
        )

    data_attributes = {
        "count": str(len(rows)),
        "total": str(page.total),
        "limit": str(page.limit),
        "offset": str(page.offset),
        "query": query,
        "sources": ",".join(resolved_sources),
    }

    fragment = TableFragment(
        identifier="hx-search-results",
        table=table,
        empty_state_key="search.results",
        data_attributes=data_attributes,
        pagination=pagination,
    )

    return {"request": request, "fragment": fragment}


__all__ = [
    "build_search_page_context",
    "build_search_results_context",
]
