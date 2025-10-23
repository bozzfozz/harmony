# Repository Maintenance Guide

## Lokale Quality Gates

Harmony besitzt keine externe Build-Pipeline. Maintainer prüfen eingehende Beiträge anhand nachvollziehbarer Logs.

| Pflichtlauf | Zweck |
| ------------ | ----- |
| `make doctor` | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline freundlich) aus und verifiziert `/data/downloads` & `/data/music` via Schreib-/Lesetest. |
| `make ui-guard` | Verhindert Platzhalterstrings in Templates, blockiert `/api/...` HTMX-Aufrufe und stellt sicher, dass statische Assets vorhanden sind. |
| `make ui-smoke` | Startet die App lokal und ruft `/live`, `/ui` sowie UI-Fragmente ab; schlägt fehl, wenn HTML-Antworten Platzhalter enthalten oder kein `text/html` liefern. |
| `make all` | Führt Formatierung, Lint, Dependency-Sync, Backend-Tests, Supply-Guard und Smoke-Test aus. |
| `make release-check` | Kombiniert `make all`, `make docs-verify`, `make pip-audit` sowie einen abschließenden `make ui-smoke` und dient als finales Release-Gate. |
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

- `make release-check` führt `pip-audit` bereits für alle verfügbaren `requirements*.txt`-Dateien aus. Dokumentiere erkannte
  Schwachstellen direkt im PR, falls der Lauf fehlschlägt.
- Generiere auf Wunsch SBOMs über `pip install cyclonedx-bom` und dokumentiere externe Bezugsquellen der Python-Abhängigkeiten.

## Release Checklist

1. Versionierung & CHANGELOG aktualisieren.
2. `make release-check` (inkl. `docs-verify`, `pip-audit` und UI-Smoketest) und optionale Security-Scans erneut ausführen.
3. Packaging-Workflow nachvollziehen:
   - `pip install .`
   - `pip wheel . -w dist/`
   - `python -m build`
4. Releases/Tarballs manuell hochladen und Release Notes verfassen (Highlights, Breaking Changes, Rollback-Plan).

## Operational Ownership

- **Primary Owner:** Internes Harmony Operations Team (siehe privates Ownership-Register).
- **Bereitschaft:** On-Call-Rotation laut internem Ops-Kalender; benachrichtigen Sie die diensthabende Person über Hotline oder On-Call-Tool.
- **Koordination:** Bei ausbleibender Rückmeldung eskaliert die Bereitschaft an die Plattform-Leitung über den Incident-Bridge-Anruf (`ops-bridge`).
- **Dokumentation:** Alle Wartungsarbeiten und Eskalationen werden im privaten Ops-Journal protokolliert; es existiert kein öffentlicher Kontaktkanal.
- **Monitoring:** Stichprobenartig die ersten PRs nach Tooling-Updates prüfen, damit Laufzeiten und Anforderungen realistisch bleiben.
