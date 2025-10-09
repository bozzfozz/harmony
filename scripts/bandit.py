#!/usr/bin/env python3
"""Offline Bandit CLI wrapper.

Loads the vendored Bandit implementation without requiring wheel installation.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_PATH = REPO_ROOT / "vendor" / "bandit_offline"
if not VENDOR_PATH.exists():
    raise SystemExit(
        "Vendored Bandit-Paket fehlt: erwartete "
        f"{VENDOR_PATH}. Bitte Repository vollständig auschecken."
    )

vendor_str = str(VENDOR_PATH)
if vendor_str not in sys.path:
    sys.path.insert(0, vendor_str)

from bandit.cli import main  # type: ignore[misc]


if __name__ == "__main__":
    raise SystemExit(main())
