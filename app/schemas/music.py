"""Typed dictionaries representing normalized music metadata."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class Track(TypedDict, total=False):
    """Normalized representation of a track across integrations."""

    title: str
    artists: list[str]
    source: Literal["slskd"] | str
    external_id: str
    album: NotRequired[str]
    duration_s: NotRequired[int]
    bitrate_kbps: NotRequired[int]
    size_bytes: NotRequired[int]
    magnet_or_path: NotRequired[str]
    score: NotRequired[float]
