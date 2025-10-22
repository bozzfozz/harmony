from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

KpiDeltaVariant = Literal["neutral", "positive", "negative"]
KpiBadgeVariant = Literal["neutral", "success", "warning", "danger", "muted"]


@dataclass(slots=True)
class KpiCard:
    identifier: str
    title: str
    value: str
    change: str | None = None
    change_variant: KpiDeltaVariant = "neutral"
    description: str | None = None
    badge_label: str | None = None
    badge_variant: KpiBadgeVariant = "neutral"
    test_id: str | None = None


@dataclass(slots=True)
class SidebarItem:
    identifier: str
    label: str
    href: str
    description: str | None = None
    test_id: str | None = None


@dataclass(slots=True)
class SidebarSection:
    identifier: str
    title: str
    description: str | None = None
    body: str | None = None
    items: Sequence[SidebarItem] = field(default_factory=tuple)


@dataclass(slots=True)
class DetailPanel:
    identifier: str
    title: str
    body: str
    subtitle: str | None = None
    footer: str | None = None


__all__ = [
    "KpiBadgeVariant",
    "KpiCard",
    "KpiDeltaVariant",
    "DetailPanel",
    "SidebarItem",
    "SidebarSection",
]
