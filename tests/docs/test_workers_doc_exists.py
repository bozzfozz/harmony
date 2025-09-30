from __future__ import annotations

from pathlib import Path


def test_workers_doc_exists() -> None:
    doc_path = Path("docs/workers.md")
    contents = doc_path.read_text(encoding="utf-8")

    assert contents.startswith("# Background Workers")
    for section in (
        "## Überblick",
        "## Lebenszyklus & Steuerung",
        "## ENV-Variablen & Defaults",
        "## Beispiel-Profile",
        "## Troubleshooting",
    ):
        assert section in contents
