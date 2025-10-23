#!/usr/bin/env python3
"""Validate that documentation links reference existing repository paths."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
CITATION_PATTERN = re.compile(r"【F:([^†】]+)")
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


@dataclass(slots=True)
class Reference:
    """A resolved reference extracted from a documentation file."""

    source: Path
    line: int
    target: str
    resolved_path: Path | None
    kind: str


def _default_paths() -> list[Path]:
    return [REPO_ROOT / "CHANGELOG.md", REPO_ROOT / "docs" / "project_status.md"]


def _compute_line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _resolve_relative(base: Path, target: str) -> Path | None:
    try:
        candidate = (base / Path(target)).resolve()
    except ValueError:
        return None
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError:
        return None
    return candidate


def _iter_citations(path: Path, text: str) -> Iterable[Reference]:
    for match in CITATION_PATTERN.finditer(text):
        raw = match.group(1).strip()
        candidate = raw.split("†", 1)[0].split("#", 1)[0].strip()
        if not candidate:
            continue
        resolved = _resolve_relative(REPO_ROOT, candidate)
        yield Reference(
            source=path,
            line=_compute_line(text, match.start()),
            target=candidate,
            resolved_path=resolved,
            kind="citation",
        )


def _iter_markdown_links(path: Path, text: str) -> Iterable[Reference]:
    base = path.parent
    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        raw = match.group(1).strip()
        if not raw or raw.startswith(("http://", "https://", "mailto:", "tel:", "#")):
            continue
        cleaned = raw.split("#", 1)[0].split("?", 1)[0].strip()
        if not cleaned:
            continue
        resolved = _resolve_relative(base, cleaned)
        yield Reference(
            source=path,
            line=_compute_line(text, match.start()),
            target=cleaned,
            resolved_path=resolved,
            kind="link",
        )


def _load_targets(paths: Iterable[Path]) -> list[Reference]:
    references: list[Reference] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Documentation file not found: {path}")
        text = path.read_text(encoding="utf-8")
        references.extend(_iter_citations(path, text))
        references.extend(_iter_markdown_links(path, text))
    return references


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Documentation files to validate")
    args = parser.parse_args(argv)

    if args.paths:
        targets = [
            (_path if _path.is_absolute() else (REPO_ROOT / _path)).resolve()
            for _path in args.paths
        ]
    else:
        targets = _default_paths()

    try:
        references = _load_targets(targets)
    except FileNotFoundError as exc:
        print(f"[docs-reference-guard] {exc}", file=sys.stderr)
        return 1

    failures = [
        ref for ref in references if ref.resolved_path is None or not ref.resolved_path.exists()
    ]

    if failures:
        for ref in failures:
            rel_source = ref.source.relative_to(REPO_ROOT)
            print(
                (
                    "[docs-reference-guard] missing "
                    f"{ref.kind}: {rel_source}:{ref.line} → {ref.target}"
                ),
                file=sys.stderr,
            )
        return 1

    print("[docs-reference-guard] all references resolved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
