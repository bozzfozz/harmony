from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import Request

from app.ui.session import UiFeatures, UiSession

AlertLevel = Literal["info", "success", "warning", "error"]
ButtonMethod = Literal["get", "post"]
StatusVariant = Literal["success", "danger", "muted"]


@dataclass(slots=True)
class NavItem:
    label_key: str
    href: str
    active: bool = False
    test_id: str | None = None


@dataclass(slots=True)
class NavigationContext:
    primary: Sequence[NavItem] = field(default_factory=tuple)


@dataclass(slots=True)
class AlertMessage:
    level: AlertLevel
    text: str


@dataclass(slots=True)
class MetaTag:
    name: str
    content: str


@dataclass(slots=True)
class ModalDefinition:
    identifier: str
    title_key: str
    body: str


@dataclass(slots=True)
class LayoutContext:
    page_id: str
    role: str | None
    navigation: NavigationContext = field(default_factory=NavigationContext)
    alerts: Sequence[AlertMessage] = field(default_factory=tuple)
    head_meta: Sequence[MetaTag] = field(default_factory=tuple)
    modals: Sequence[ModalDefinition] = field(default_factory=tuple)


@dataclass(slots=True)
class FormField:
    name: str
    input_type: str
    label_key: str
    autocomplete: str | None = None
    required: bool = False


@dataclass(slots=True)
class FormDefinition:
    identifier: str
    method: ButtonMethod
    action: str
    submit_label_key: str
    fields: Sequence[FormField] = field(default_factory=tuple)


@dataclass(slots=True)
class ActionButton:
    identifier: str
    label_key: str


@dataclass(slots=True)
class StatusBadge:
    label_key: str
    variant: StatusVariant
    test_id: str | None = None


@dataclass(slots=True)
class TableCell:
    text_key: str | None = None
    text: str | None = None
    badge: StatusBadge | None = None
    test_id: str | None = None


@dataclass(slots=True)
class TableRow:
    cells: Sequence[TableCell]
    test_id: str | None = None


@dataclass(slots=True)
class TableDefinition:
    identifier: str
    column_keys: Sequence[str]
    rows: Sequence[TableRow]
    caption_key: str | None = None


def build_login_page_context(request: Request, *, error: str | None = None) -> Mapping[str, Any]:
    alerts: list[AlertMessage] = []
    if error:
        alerts.append(AlertMessage(level="error", text=error))

    layout = LayoutContext(
        page_id="login",
        role="anonymous",
        alerts=tuple(alerts),
    )

    login_form = FormDefinition(
        identifier="login-form",
        method="post",
        action="/ui/login",
        submit_label_key="login.submit",
        fields=(
            FormField(
                name="api_key",
                input_type="password",
                label_key="login.api_key",
                autocomplete="off",
                required=True,
            ),
        ),
    )

    return {
        "request": request,
        "layout": layout,
        "form": login_form,
    }


def build_dashboard_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    navigation_items: list[NavItem] = [
        NavItem(label_key="nav.home", href="/ui", active=True, test_id="nav-home"),
    ]
    actions: list[ActionButton] = []

    if session.allows("operator"):
        navigation_items.append(
            NavItem(
                label_key="nav.operations",
                href="/ui/operations",
                test_id="nav-operator",
            )
        )
        actions.append(
            ActionButton(
                identifier="operator-action",
                label_key="dashboard.action.operator",
            )
        )

    if session.allows("admin"):
        navigation_items.append(
            NavItem(
                label_key="nav.admin",
                href="/ui/admin",
                test_id="nav-admin",
            )
        )
        actions.append(
            ActionButton(
                identifier="admin-action",
                label_key="dashboard.action.admin",
            )
        )

    layout = LayoutContext(
        page_id="dashboard",
        role=session.role,
        navigation=NavigationContext(primary=tuple(navigation_items)),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    features_table = _build_features_table(session.features)

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "features_table": features_table,
        "actions": tuple(actions),
    }


def _build_features_table(features: UiFeatures) -> TableDefinition:
    feature_rows = [
        ("feature.spotify", features.spotify, "spotify"),
        ("feature.soulseek", features.soulseek, "soulseek"),
        ("feature.dlq", features.dlq, "dlq"),
        ("feature.imports", features.imports, "imports"),
    ]

    rows = [
        TableRow(
            cells=(
                TableCell(text_key=label_key, test_id=f"feature-{slug}"),
                TableCell(
                    badge=StatusBadge(
                        label_key="status.enabled" if enabled else "status.disabled",
                        variant="success" if enabled else "muted",
                        test_id=f"feature-{slug}-status",
                    )
                ),
            ),
        )
        for label_key, enabled, slug in feature_rows
    ]

    return TableDefinition(
        identifier="features-table",
        column_keys=("dashboard.features.name", "dashboard.features.status"),
        rows=tuple(rows),
        caption_key="dashboard.features.caption",
    )


__all__ = [
    "ActionButton",
    "AlertMessage",
    "FormDefinition",
    "FormField",
    "LayoutContext",
    "NavigationContext",
    "NavItem",
    "StatusBadge",
    "TableCell",
    "TableDefinition",
    "TableRow",
    "build_dashboard_page_context",
    "build_login_page_context",
]
