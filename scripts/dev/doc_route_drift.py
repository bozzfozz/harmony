#!/usr/bin/env python3
"""Generate a documentation drift report for API routes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from fastapi.routing import APIRoute

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "reports" / "api" / "doc_route_drift.md"
TARGET_DOCUMENTS = (
    REPO_ROOT / "docs" / "ui" / "fe-htmx-plan.md",
    REPO_ROOT / "reports" / "ui" / "frontend_inventory.md",
)

_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_./])(/api/[^\s`]+)")
_SKIP_SUBSTRINGS = ("...", "…")
_STRIP_CHARS = "`*_()[]<>.,;'\""
_PARAM_PATTERN = re.compile(r"\{[^{}]+\}")
_SKIP_EXACT_PATHS = {"/api/health"}

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class DocRoute:
    """API route reference extracted from documentation."""

    document: Path
    path: str
    line_number: int
    context: str


@dataclass(frozen=True)
class DriftFinding:
    """A documentation reference that could not be matched to a real route."""

    document: Path
    path: str
    context: str


def _normalize_route_path(path: str) -> str:
    if path == "/":
        return path
    return path.rstrip("/")


def _canonicalize_path(path: str) -> str:
    return _PARAM_PATTERN.sub("{}", path)


def _normalize_doc_candidate(candidate: str) -> list[str]:
    stripped = candidate.strip()
    for token in _SKIP_SUBSTRINGS:
        if token in stripped:
            return []
    cleaned = stripped.strip(_STRIP_CHARS)
    if not cleaned.startswith("/api/"):
        return []
    if cleaned in _SKIP_EXACT_PATHS:
        return []
    cleaned = cleaned.replace("\\|", "|")
    if "|" in cleaned:
        head, _, tail = cleaned.rpartition("/")
        if not head or not tail:
            return []
        options = [segment.strip() for segment in tail.split("|") if segment.strip()]
        return [_normalize_route_path(f"{head}/{option}") for option in options]
    return [_normalize_route_path(cleaned)]


def _gather_actual_routes() -> set[str]:
    from app.main import app  # local import to avoid side effects at module load

    discovered: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        normalized = _normalize_route_path(route.path)
        if not normalized.startswith("/api/"):
            continue
        discovered.add(_canonicalize_path(normalized))
    return discovered


def _iter_documents(documents: Iterable[Path]) -> Iterable[Path]:
    for document in documents:
        if not document.exists():
            print(f"warning: skipped missing document {document}", file=sys.stderr)
            continue
        yield document


def _scan_document(path: Path) -> list[DocRoute]:
    text = path.read_text(encoding="utf-8").splitlines()
    references: list[DocRoute] = []
    relative_path = path.relative_to(REPO_ROOT)
    for index, line in enumerate(text, start=1):
        for match in _PATH_PATTERN.finditer(line):
            raw_path = match.group(1)
            for normalized in _normalize_doc_candidate(raw_path):
                references.append(
                    DocRoute(
                        document=relative_path,
                        path=normalized,
                        line_number=index,
                        context=line.strip(),
                    )
                )
    return references


def _unique_references(entries: Iterable[DocRoute]) -> list[DocRoute]:
    seen: set[tuple[Path, str]] = set()
    unique: list[DocRoute] = []
    for entry in entries:
        key = (entry.document, entry.path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _detect_drift(doc_references: list[DocRoute], actual_routes: set[str]) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    for reference in doc_references:
        canonical = _canonicalize_path(reference.path)
        if canonical in actual_routes:
            continue
        if "{" not in reference.path:
            candidate_with_param = _canonicalize_path(
                f"{_normalize_route_path(reference.path)}/{{}}"
            )
            if candidate_with_param in actual_routes:
                continue
        findings.append(
            DriftFinding(
                document=reference.document,
                path=reference.path,
                context=reference.context,
            )
        )
    return findings


def _build_report(findings: list[DriftFinding], scanned_documents: list[Path]) -> str:
    header = ["# API Documentation Route Drift", ""]
    if findings:
        header.append(
            "The repository scan detected documentation references that do not map to FastAPI routes."  # noqa: E501
        )
        header.append("")
        header.append("| Document | Documented Path | Note |")
        header.append("| --- | --- | --- |")
        for finding in sorted(findings, key=lambda item: (str(item.document), item.path)):
            note = f"Missing in routing table (context: {finding.context})"
            header.append(f"| `{finding.document.as_posix()}` | `{finding.path}` | {note} |")
        header.append("")
        header.append(
            "Run `scripts/dev/doc_route_drift.py` after updating documentation or routes "
            "to refresh this report."
        )
    else:
        header.append(
            "No discrepancies detected between the scanned documentation and the FastAPI routing table."  # noqa: E501
        )
        header.append("")
        header.append("Scanned documents:")
        for document in scanned_documents:
            header.append(f"- `{document.as_posix()}`")
        header.append("")
        header.append(
            "Verification generated via `scripts/dev/doc_route_drift.py`, which loads "
            "`app.main` to read the active route table."
        )
    header.append("")
    return "\n".join(header)


def main() -> int:
    documents = list(_iter_documents(TARGET_DOCUMENTS))
    if not documents:
        print("error: no documentation sources found", file=sys.stderr)
        return 1

    actual_routes = _gather_actual_routes()

    doc_references: list[DocRoute] = []
    for document in documents:
        doc_references.extend(_scan_document(document))

    unique_references = _unique_references(doc_references)
    findings = _detect_drift(unique_references, actual_routes)
    report = _build_report(findings, [doc.relative_to(REPO_ROOT) for doc in documents])
    OUTPUT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")

    if findings:
        print(
            "documentation drift detected; inspect reports/api/doc_route_drift.md for details",
            file=sys.stderr,
        )
        return 1

    print("No documentation drift detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
