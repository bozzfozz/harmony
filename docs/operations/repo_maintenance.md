# Repository Maintenance Guide

## Lokale Quality Gates

Harmony besitzt keine externe Build-Pipeline. Maintainer prüfen eingehende Beiträge anhand nachvollziehbarer Logs.

| Pflichtlauf | Zweck |
| ------------ | ----- |
| `make doctor` | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline freundlich) aus und verifiziert `/data/downloads` & `/data/music` via Schreib-/Lesetest. |
| `make all` | Führt Formatierung, Lint, Dependency-Sync, Backend-Tests, Supply-Guard und Smoke-Test aus. |
| `pre-commit run --all-files` | Spiegelt alle Commit-Hooks (`ruff-format`, `ruff`, lokale Skripte). |
| `pre-commit run --hook-stage push` | Führt `scripts/dev/test_py.sh` vor dem Push aus. |

## Branch Protection & Evidence

- Es sind keine Required-Status-Checks konfiguriert. Maintainer verifizieren stattdessen die angehängten Logs der oben genannten Läufe.
- PRs ohne Wiring-/Removal-Report oder ohne Logs der Pflichtläufe dürfen nicht gemergt werden.
- Speichere relevante Terminalausgaben in `reports/` (aus dem `.gitignore`) oder im PR-Body.

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
pre-commit run --all-files
pre-commit run --hook-stage push
```

- Lokale Hooks rufen `scripts/dev/fmt.sh` und `scripts/dev/dep_sync_py.sh` auf.
- Der Pre-Push-Hook startet `scripts/dev/test_py.sh`. Bei Fehlern werden Pushes abgebrochen.

## Manuelle Nightly-/Security-Checks

- Führe `pip-audit -r requirements.txt` bei Bedarf lokal aus und dokumentiere die Ergebnisse im PR.
- Generiere auf Wunsch SBOMs über `pip install cyclonedx-bom` und dokumentiere externe Bezugsquellen der Python-Abhängigkeiten.

## Release Checklist

1. Versionierung & CHANGELOG aktualisieren.
2. `make all` und optionale Security-Scans erneut ausführen.
3. Artefakte erstellen:
   - Python: `python -m build`
4. Releases/Tarballs manuell hochladen und Release Notes verfassen (Highlights, Breaking Changes, Rollback-Plan).

## Operational Ownership

- **Primary Owner:** Team Platform Engineering.
- **Escalation:** Melde Probleme im Channel `#harmony-platform` und verweise auf Logs aus `make all`.
- **Monitoring:** Stichprobenartig die ersten PRs nach Tooling-Updates prüfen, damit Laufzeiten und Anforderungen realistisch bleiben.
