"""Helpers for ingesting Spotify playlist links in FREE mode."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Iterable, List, Sequence
from urllib.parse import urlparse

__all__ = [
    "PlaylistLink",
    "RejectedLink",
    "ParseResult",
    "TooManyItemsError",
    "InvalidPayloadError",
    "parse_and_validate_links",
]


@dataclass(slots=True)
class PlaylistLink:
    """Represents an accepted playlist link."""

    original: str
    playlist_id: str


@dataclass(slots=True)
class RejectedLink:
    """Represents an invalid playlist submission."""

    url: str
    reason: str


@dataclass(slots=True)
class ParseResult:
    """Outcome of parsing a FREE ingest payload."""

    accepted: List[PlaylistLink]
    rejected: List[RejectedLink]
    skipped: List[str]
    total_links: int


class TooManyItemsError(Exception):
    """Raised when a payload exceeds the hard link cap."""

    def __init__(self, provided: int, limit: int) -> None:
        self.provided = provided
        self.limit = limit
        super().__init__(f"received {provided} links which exceeds hard limit {limit}")


class InvalidPayloadError(Exception):
    """Raised when a payload cannot be parsed into playlist links."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def parse_and_validate_links(
    *,
    raw_body: bytes,
    content_type: str | None,
    max_links: int,
    hard_cap_links: int,
    allow_user_urls: bool,
) -> ParseResult:
    """Parse the request payload and validate Spotify playlist links."""

    candidates = list(
        _extract_links_from_payload(raw_body=raw_body, content_type=content_type)
    )
    total_candidates = len(candidates)

    if total_candidates > hard_cap_links:
        raise TooManyItemsError(total_candidates, hard_cap_links)

    accepted: List[PlaylistLink] = []
    accepted_ids: set[str] = set()
    rejected: List[RejectedLink] = []
    skipped: List[str] = []

    for candidate in candidates:
        text = candidate.strip()
        if not text:
            rejected.append(RejectedLink(url=candidate, reason="INVALID_URL"))
            continue

        playlist_id, rejection_reason = _normalise_playlist_link(
            text,
            allow_user_urls=allow_user_urls,
        )

        if playlist_id is None:
            rejected.append(
                RejectedLink(url=text, reason=rejection_reason or "INVALID_URL")
            )
            continue

        if playlist_id in accepted_ids:
            skipped.append(text)
            continue

        if len(accepted) >= max_links:
            skipped.append(text)
            continue

        accepted.append(PlaylistLink(original=text, playlist_id=playlist_id))
        accepted_ids.add(playlist_id)

    return ParseResult(
        accepted=accepted,
        rejected=rejected,
        skipped=skipped,
        total_links=total_candidates,
    )


def _extract_links_from_payload(
    *, raw_body: bytes, content_type: str | None
) -> Iterable[str]:
    if not raw_body:
        return []

    media_type, charset = _parse_media_type(content_type)

    if media_type == "application/json":
        text = raw_body.decode(charset, errors="replace")
        return _extract_links_from_json(text)

    text = raw_body.decode(charset, errors="replace")

    if media_type == "text/csv":
        reader = csv.reader(io.StringIO(text))
        return [item.strip() for row in reader for item in row]

    # Default to line-based text parsing
    return [line for line in text.splitlines()]


def _extract_links_from_json(text: str) -> Sequence[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise InvalidPayloadError("INVALID_JSON") from exc

    if not isinstance(payload, dict):
        raise InvalidPayloadError("INVALID_JSON_STRUCTURE")

    links = payload.get("links")
    if links is None:
        raise InvalidPayloadError("MISSING_LINKS_FIELD")

    if not isinstance(links, list):
        raise InvalidPayloadError("INVALID_LINKS_TYPE")

    result: list[str] = []
    for item in links:
        result.append(str(item))
    return result


def _parse_media_type(content_type: str | None) -> tuple[str, str]:
    if not content_type:
        return "text/plain", "utf-8"

    parts = [part.strip() for part in content_type.split(";") if part.strip()]
    media_type = parts[0].lower() if parts else "text/plain"
    charset = "utf-8"

    for part in parts[1:]:
        if part.lower().startswith("charset="):
            candidate = part.split("=", 1)[1].strip()
            if candidate:
                charset = candidate.lower()
            break

    return media_type, charset


def _normalise_playlist_link(
    link: str,
    *,
    allow_user_urls: bool,
) -> tuple[str | None, str | None]:
    lowered = link.lower()

    if lowered.startswith("spotify:"):
        parts = link.split(":")
        if len(parts) < 3:
            return None, "INVALID_URL"

        kind = parts[1].lower()
        if kind == "playlist":
            playlist_id = parts[2]
            if not _is_valid_playlist_id(playlist_id):
                return None, "INVALID_PLAYLIST_ID"
            return playlist_id, None

        if kind == "user":
            if not allow_user_urls:
                return None, "NOT_A_PLAYLIST_URL"
            if len(parts) < 5:
                return None, "INVALID_URL"
            if parts[3].lower() != "playlist":
                return None, "NOT_A_PLAYLIST_URL"
            playlist_id = parts[4]
            if not _is_valid_playlist_id(playlist_id):
                return None, "INVALID_PLAYLIST_ID"
            return playlist_id, None

        return None, "NOT_A_PLAYLIST_URL"

    if lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(link)
        if parsed.netloc.lower() != "open.spotify.com":
            return None, "UNSUPPORTED_URL"

        segments = [segment for segment in parsed.path.split("/") if segment]
        if segments and segments[0].lower().startswith("intl-"):
            segments = segments[1:]
        if not segments:
            return None, "NOT_A_PLAYLIST_URL"

        kind = segments[0].lower()
        if kind == "playlist":
            if len(segments) < 2:
                return None, "INVALID_PLAYLIST_ID"

            playlist_id = segments[1]
            playlist_id = playlist_id.split("?")[0].split("#")[0]
            if not _is_valid_playlist_id(playlist_id):
                return None, "INVALID_PLAYLIST_ID"
            return playlist_id, None

        if kind == "user":
            if not allow_user_urls:
                return None, "NOT_A_PLAYLIST_URL"
            if len(segments) < 4:
                return None, "INVALID_PLAYLIST_ID"
            if segments[2].lower() != "playlist":
                return None, "NOT_A_PLAYLIST_URL"
            playlist_id = segments[3]
            playlist_id = playlist_id.split("?")[0].split("#")[0]
            if not _is_valid_playlist_id(playlist_id):
                return None, "INVALID_PLAYLIST_ID"
            return playlist_id, None

        return None, "NOT_A_PLAYLIST_URL"

    if "spotify" in lowered:
        return None, "INVALID_URL"

    return None, "UNSUPPORTED_URL"


def _is_valid_playlist_id(playlist_id: str) -> bool:
    return playlist_id.isalnum()
