#!/usr/bin/env python3
"""Fail if archived integrations leak into active wiring."""

from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRECTORIES = ["app", "tests"]
FORBIDDEN_PATTERNS = {
    "plex": re.compile(r"\bplex\b", re.IGNORECASE),
    "beets": re.compile(r"\bbeets\b", re.IGNORECASE),
    "beet ": re.compile(r"\bbeet\s", re.IGNORECASE),
    "scan_worker": re.compile(r"scan_worker"),
}

ALEMBIC_VERSIONS_DIR = REPO_ROOT / "app" / "migrations" / "versions"


@dataclass(frozen=True)
class Allowance:
    path: Path
    pattern: re.Pattern[str]

    def matches(self, file_path: Path, line: str) -> bool:
        if file_path != self.path:
            return False
        return bool(self.pattern.search(line))


ALLOWANCES: tuple[Allowance, ...] = (
    Allowance(Path("app/main.py"), re.compile(r"wiring_summary .*plex=false")),
    Allowance(Path("app/main.py"), re.compile(r'"plex"\s*:\s*False')),
    Allowance(Path("tests/test_matching.py"), re.compile(r"spotify-to-plex")),
    Allowance(Path("tests/test_matching.py"), re.compile(r"discography/plex")),
)


def iter_candidate_files() -> Iterable[Path]:
    for directory in SCAN_DIRECTORIES:
        base = REPO_ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_dir():
                continue
            relative = path.relative_to(REPO_ROOT)
            if "archive" in relative.parts:
                continue
            yield relative


def line_is_allowed(path: Path, line: str) -> bool:
    return any(allowance.matches(path, line) for allowance in ALLOWANCES)


def _parse_down_revision(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (tuple, list)):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
        return result
    return []


def _extract_revision_metadata(path: Path) -> tuple[str | None, object | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    revision: str | None = None
    down_revision: object | None = None

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "revision":
            revision = ast.literal_eval(node.value)
        elif target.id == "down_revision":
            down_revision = ast.literal_eval(node.value)

    return revision, down_revision


def _check_alembic_reset_guard() -> list[str]:
    guard = os.getenv("MIGRATION_RESET")
    if guard == "1":
        return []

    if not ALEMBIC_VERSIONS_DIR.exists():
        return [
            "Alembic guard: versions directory missing; set MIGRATION_RESET=1 to bypass during resets.",
        ]

    revision_files = sorted(
        path
        for path in ALEMBIC_VERSIONS_DIR.iterdir()
        if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
    )

    if not revision_files:
        return [
            "Alembic guard: expected at least one revision file under app/migrations/versions.",
        ]

    revisions: dict[str, Path] = {}
    down_revisions: dict[str, list[str]] = {}
    errors: list[str] = []

    for revision_file in revision_files:
        try:
            revision, down_revision = _extract_revision_metadata(revision_file)
        except (
            OSError,
            SyntaxError,
            ValueError,
        ) as exc:  # pragma: no cover - defensive guard
            errors.append(
                (
                    "Alembic guard: unable to parse revision metadata from {path}: {error}."
                ).format(path=revision_file.name, error=exc)
            )
            continue

        if not revision:
            errors.append(
                "Alembic guard: revision identifier missing in {path}.".format(
                    path=revision_file.name
                )
            )
            continue

        revisions[revision] = revision_file
        down_revisions[revision] = _parse_down_revision(down_revision)

    if errors:
        return errors

    referenced: set[str] = set()
    for revision, parents in down_revisions.items():
        for parent in parents:
            referenced.add(parent)
            if parent not in revisions:
                errors.append(
                    "Alembic guard: {child} references missing down_revision {parent}.".format(
                        child=revision, parent=parent
                    )
                )

    if errors:
        return errors

    bases = [rev for rev, parents in down_revisions.items() if not parents]
    if len(bases) != 1:
        errors.append(
            (
                "Alembic guard: expected exactly one base revision (down_revision=None); found {count} ({details})."
            ).format(count=len(bases), details=", ".join(sorted(bases)) or "none")
        )

    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        errors.append(
            (
                "Alembic guard: expected a single migration head but found {count} ({details})."
            ).format(count=len(heads), details=", ".join(heads) or "none")
        )

    return errors


def main() -> int:
    violations: list[str] = []

    for relative_path in iter_candidate_files():
        absolute_path = REPO_ROOT / relative_path
        try:
            content = absolute_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(content.splitlines(), start=1):
            for label, pattern in FORBIDDEN_PATTERNS.items():
                if not pattern.search(line):
                    continue
                if line_is_allowed(relative_path, line):
                    continue
                violations.append(
                    f"{relative_path}:{index}: forbidden reference '{label}'"
                )
                break

    violations.extend(_check_alembic_reset_guard())

    if violations:
        for violation in violations:
            print(violation)
        print(
            "\nWiring audit failed. Remove legacy Plex/Beets references or update the allowlist",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
