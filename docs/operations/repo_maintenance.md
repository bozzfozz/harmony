# Repository Maintenance Guide

## Lokale Quality Gates

Harmony nutzt den GitHub-Actions-Workflow [`backend-ci`](../../.github/workflows/ci.yml), der Formatierung, Linting, Typprüfungen, Pytests und Smoke-Checks sequenziell ausführt. Maintainer reproduzieren die einzelnen Läufe lokal und dokumentieren nachvollziehbare Logs als Ergänzung zu den CI-Artefakten.

| Pflichtlauf | Zweck |
| ------------ | ----- |
| `make doctor` | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline freundlich) aus und verifiziert `/downloads` & `/music` via Schreib-/Lesetest. |
| `make ui-guard` | Verhindert Platzhalterstrings in Templates, blockiert `/api/...` HTMX-Aufrufe und stellt sicher, dass statische Assets vorhanden sind. |
| `make ui-smoke` | Startet die App lokal und ruft `/live`, `/ui` sowie UI-Fragmente ab; schlägt fehl, wenn HTML-Antworten Platzhalter enthalten oder kein `text/html` liefern. |
| `make all` | Führt Formatierung, Lint, Dependency-Sync, Backend-Tests, Supply-Guard und Smoke-Test aus. |
| `make release-check` | Kombiniert `make all`, `make docs-verify`, `make pip-audit` sowie einen abschließenden `make ui-smoke` und dient als finales Release-Gate. |
| `make image-lsio` / `make smoke-lsio` | Erstellt das LinuxServer.io-Image (`docker/Dockerfile.lsio`) und prüft es mit einem Healthcheck- und Datenbank-Bootstrap-Lauf. |
| `pre-commit run --all-files` | Spiegelt alle Commit-Hooks (`ruff-format`, `ruff`, lokale Skripte). |
| `pre-commit run --hook-stage push` | Führt `scripts/dev/test_py.sh` vor dem Push aus. |

## Branch Protection & Evidence

- Pull Requests benötigen einen erfolgreichen Durchlauf der Required-Status-Checks `backend-ci` **und** `release-check`.
- Der Workflow [`release-check`](../../.github/workflows/release-check.yml) läuft automatisch für Branches `release/**` sowie Tags `v*`, führt `make release-check` inklusive `docs-verify`, `pip-audit` und UI-Smoke-Test aus und validiert anschließend den Packaging-Pipeline-Run via `make package-verify`.
- Die Workflow-Logs werden als Artefakt `release-check-logs` gespeichert und enthalten die Datei `reports/release-check/release-check.log` als revisionssicheren Nachweis. Zusätzlich archiviert der Workflow das Artefakt `release-packaging-artifacts` mit dem Inhalt des Verzeichnisses `dist/` für eine spätere manuelle Prüfung.
- Maintainer prüfen die GitHub-Actions-Protokolle (`backend-ci`, `release-check`) sowie die angehängten Logs der lokalen Pflichtläufe, bevor sie freigeben.
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
   - Lokal `make package-verify` ausführen (führt `pip install .`, `pip wheel . -w dist/` und `python -m build` sequenziell mit Cleanups zwischen den Schritten aus).
   - Alternativ die CI-Artefakte (`release-packaging-artifacts`) des Workflows [`release-check`](../../.github/workflows/release-check.yml) prüfen, um den letzten erfolgreichen Build zu bestätigen.
4. Releases/Tarballs manuell hochladen und Release Notes verfassen (Highlights, Breaking Changes, Rollback-Plan).

## Operational Ownership

- **Primary Owner:** Internes Harmony Operations Team (siehe privates Ownership-Register).
- **Bereitschaft:** On-Call-Rotation laut internem Ops-Kalender; benachrichtigen Sie die diensthabende Person über Hotline oder On-Call-Tool.
- **Koordination:** Bei ausbleibender Rückmeldung eskaliert die Bereitschaft an die Plattform-Leitung über den Incident-Bridge-Anruf (`ops-bridge`).
- **Dokumentation:** Alle Wartungsarbeiten und Eskalationen werden im privaten Ops-Journal protokolliert; es existiert kein öffentlicher Kontaktkanal.
- **Monitoring:** Stichprobenartig die ersten PRs nach Tooling-Updates prüfen, damit Laufzeiten und Anforderungen realistisch bleiben.
