"""Konfigurations-Helfer für den Bandit-Nachbau."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List
import configparser

from .core import ConfidenceLevel, SeverityLevel


@dataclass(slots=True)
class BanditConfig:
    """Repräsentiert die minimal benötigten Konfigurationseinstellungen."""

    targets: List[Path] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    severity: SeverityLevel = SeverityLevel.LOW
    confidence: ConfidenceLevel = ConfidenceLevel.LOW

    @classmethod
    def from_file(cls, path: Path) -> "BanditConfig":
        parser = configparser.ConfigParser()
        parser.read(path)
        if "bandit" not in parser:
            return cls()

        section = parser["bandit"]
        targets = cls._parse_path_list(section.get("targets", ""))
        exclude = cls._parse_list(section.get("exclude", ""))
        severity = SeverityLevel.from_string(section.get("severity", "LOW"))
        confidence = ConfidenceLevel.from_string(section.get("confidence", "LOW"))
        return cls(targets=list(targets), exclude=exclude, severity=severity, confidence=confidence)

    def merge_cli(
        self,
        *,
        recursive_targets: Iterable[Path],
        paths: Iterable[Path],
        exclude: Iterable[str],
        severity: str | None,
        confidence: str | None,
    ) -> "BanditConfig":
        merged_targets: list[Path] = []
        for entry in recursive_targets:
            merged_targets.append(entry)
        if not merged_targets:
            if self.targets:
                merged_targets.extend(self.targets)
            else:
                merged_targets.extend(paths)
        else:
            merged_targets.extend(paths)

        merged_exclude = list({*self.exclude, *exclude})
        merged_severity = SeverityLevel.from_string(severity) if severity else self.severity
        merged_confidence = ConfidenceLevel.from_string(confidence) if confidence else self.confidence
        return BanditConfig(
            targets=merged_targets or list(paths),
            exclude=merged_exclude,
            severity=merged_severity,
            confidence=merged_confidence,
        )

    @staticmethod
    def _parse_path_list(raw: str) -> List[Path]:
        return [Path(item.strip()) for item in BanditConfig._parse_list(raw)]

    @staticmethod
    def _parse_list(raw: str) -> List[str]:
        cleaned = raw.strip()
        if not cleaned:
            return []
        return [item.strip() for item in cleaned.replace("\n", ",").split(",") if item.strip()]
