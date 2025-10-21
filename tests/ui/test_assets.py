"""Tests ensuring static asset size budgets stay within the documented limits."""

from __future__ import annotations

import gzip
from pathlib import Path

CSS_ASSET = Path("app/ui/static/css/app.css")
# docs/ui/fe-htmx-plan.md: CSS budget ≤20 KB (uncompressed)
CSS_BUDGET_BYTES = 20 * 1024

HTMX_ASSET = Path("app/ui/static/js/htmx.min.js")
# docs/ui/fe-htmx-plan.md: gzip payload must stay ≤20 KB
HTMX_GZIP_BUDGET_BYTES = 20 * 1024


def _gzip_size(path: Path) -> int:
    """Return the gzip-compressed size of the given file in bytes."""

    return len(gzip.compress(path.read_bytes()))


def test_ui_asset_size_budgets() -> None:
    """Static UI assets should remain within their documented size budgets."""

    css_size = CSS_ASSET.stat().st_size
    assert css_size <= CSS_BUDGET_BYTES, (
        f"app.css is {css_size} bytes but the budget is {CSS_BUDGET_BYTES} bytes (≤20 KB)."
    )

    htmx_gzip_size = _gzip_size(HTMX_ASSET)
    assert htmx_gzip_size <= HTMX_GZIP_BUDGET_BYTES, (
        "htmx.min.js (gzip) is"
        f" {htmx_gzip_size} bytes but the budget is {HTMX_GZIP_BUDGET_BYTES} bytes"
        " (≤20 KB gzip)."
    )
