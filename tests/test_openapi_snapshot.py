from __future__ import annotations

import json
from pathlib import Path

from app.main import app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"


def test_openapi_snapshot() -> None:
    current_schema = app.openapi()
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    assert current_schema == snapshot
