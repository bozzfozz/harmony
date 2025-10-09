"""Eingangspunkt für den Bandit-kompatiblen CLI-Befehl."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
import argparse
import sys

from .config import BanditConfig
from .core import ConfidenceLevel, SeverityLevel, iter_python_files, scan_paths
from .report import Report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Bandit scanner")
    parser.add_argument("paths", nargs="*", type=Path, help="Zu prüfende Dateien oder Verzeichnisse")
    parser.add_argument("-r", "--recursive", action="append", dest="recursive", type=Path, default=[], help="Verzeichnisse rekursiv scannen")
    parser.add_argument("-c", "--config", type=Path, dest="config", help="Konfigurationsdatei im Bandit-Format")
    parser.add_argument("-q", "--quiet", action="store_true", help="Nur Zusammenfassung ausgeben")
    parser.add_argument("-x", "--exclude", action="append", default=[], help="Glob/Pfad der ausgeschlossen werden soll")
    parser.add_argument("--severity-level", choices=[level.name for level in SeverityLevel], help="Schweregrad-Schwelle überschreiben")
    parser.add_argument("--confidence-level", choices=[level.name for level in ConfidenceLevel], help="Vertrauens-Schwelle überschreiben")
    return parser


def collect_targets(config: BanditConfig) -> List[Path]:
    if not config.targets:
        raise SystemExit("Keine Zielpfade angegeben. Verwende -r oder reiche einzelne Dateien ein.")
    return list(dict.fromkeys(config.targets))


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = BanditConfig.from_file(args.config) if args.config else BanditConfig()
    merged = config.merge_cli(
        recursive_targets=args.recursive,
        paths=args.paths,
        exclude=args.exclude,
        severity=args.severity_level,
        confidence=args.confidence_level,
    )

    targets = collect_targets(merged)
    files = list(iter_python_files(targets, merged.exclude))
    issues = scan_paths(files)
    report = Report(issues, merged.severity, merged.confidence)
    report.render(sys.stdout, quiet=args.quiet)
    return 1 if report.has_issues() else 0
