#!/usr/bin/env python3
"""Fail if archived integrations leak into active wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRECTORIES = ["app", "tests"]
FORBIDDEN_PATTERNS = {
    "plex": re.compile(r"\bplex\b", re.IGNORECASE),
    "beets": re.compile(r"\bbeets\b", re.IGNORECASE),
    "beet ": re.compile(r"\bbeet\s", re.IGNORECASE),
    "scan_worker": re.compile(r"scan_worker"),
}


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
                violations.append(f"{relative_path}:{index}: forbidden reference '{label}'")
                break

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
