"""Berichtserstellung für den Bandit-Ersatz."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, TextIO

from .core import BanditIssue, ConfidenceLevel, SeverityLevel


@dataclass(slots=True)
class Report:
    issues: List[BanditIssue]
    severity_threshold: SeverityLevel
    confidence_threshold: ConfidenceLevel

    def filtered(self) -> List[BanditIssue]:
        return [
            issue
            for issue in self.issues
            if issue.severity >= self.severity_threshold and issue.confidence >= self.confidence_threshold
        ]

    def render(self, stream: TextIO, *, quiet: bool = False) -> None:
        matches = self.filtered()
        if not matches:
            stream.write("No issues identified.\n")
            stream.write(
                f"0 issue(s) with severity >= {self.severity_threshold.name} "
                f"and confidence >= {self.confidence_threshold.name}.\n"
            )
            return

        if not quiet:
            for issue in sorted(matches, key=_issue_sort_key):
                rel_path = _relative(issue.filename)
                stream.write(
                    f"{rel_path}:{issue.lineno}:{issue.col_offset}: "
                    f"{issue.test_id} [{issue.severity.name}/{issue.confidence.name}] {issue.message}\n"
                )

        stream.write(
            f"\n{len(matches)} issue(s) with severity >= {self.severity_threshold.name} "
            f"and confidence >= {self.confidence_threshold.name}.\n"
        )

    def has_issues(self) -> bool:
        return bool(self.filtered())


def _issue_sort_key(issue: BanditIssue) -> tuple[int, str, int, int]:
    return (-int(issue.severity), str(issue.filename), issue.lineno, issue.col_offset)


def _relative(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd())
    except ValueError:
        return path


def summarize(issues: Iterable[BanditIssue]) -> tuple[int, int, int]:
    severity_counts = {SeverityLevel.LOW: 0, SeverityLevel.MEDIUM: 0, SeverityLevel.HIGH: 0}
    for issue in issues:
        severity_counts[issue.severity] += 1
    return severity_counts[SeverityLevel.LOW], severity_counts[SeverityLevel.MEDIUM], severity_counts[SeverityLevel.HIGH]
