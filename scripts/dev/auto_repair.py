#!/usr/bin/env python3
"""CLI wrapper for the auto-repair engine."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _run() -> int:
    from scripts.auto_repair.engine import main

    return main()


if __name__ == "__main__":
    sys.exit(_run())
