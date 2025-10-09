from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

from app.api.admin_artists import maybe_register_admin_routes
from app.config import AppConfig
from app.dependencies import get_app_config
from app.main import app


@contextmanager
def openapi_flag_context(
    *, enable_admin_api: bool | None = None
) -> Iterator[AppConfig]:
    """Temporarily override the OpenAPI configuration flags for tests."""

    original_config = getattr(app.state, "openapi_config", None)
    if isinstance(original_config, AppConfig):
        base_config = deepcopy(original_config)
    else:
        base_config = deepcopy(get_app_config())

    if enable_admin_api is not None:
        base_config.features = replace(
            base_config.features, enable_admin_api=enable_admin_api
        )
        base_config.admin = replace(base_config.admin, api_enabled=enable_admin_api)

    app.state.openapi_config = deepcopy(base_config)
    app.openapi_schema = None
    maybe_register_admin_routes(app, config=base_config)
    try:
        yield base_config
    finally:
        restored_config: AppConfig
        if isinstance(original_config, AppConfig):
            restored_config = deepcopy(original_config)
        else:
            restored_config = get_app_config()
        app.state.openapi_config = deepcopy(restored_config)
        app.openapi_schema = None
        maybe_register_admin_routes(app, config=restored_config)
