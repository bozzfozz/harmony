# Repository Maintenance Guide

## Lokale Quality Gates

Harmony nutzt den GitHub-Actions-Workflow [`release-check`](../../.github/workflows/release-check.yml), der `uv run make release-check` inklusive Formatierung, Linting, Typprüfungen, Tests, Smoke, Dokumentations-Guard, Security-Scan und UI-Smoketest ausführt. Das optionale [`docker-image`](../../.github/workflows/docker-image.yml) Workflow wiederholt denselben Gate-Lauf, bevor Container-Builds entstehen. Maintainer reproduzieren die einzelnen Läufe lokal und dokumentieren nachvollziehbare Logs als Ergänzung zu den CI-Artefakten. Der Standard-Gate-Lauf besteht lokal aus `uv run pip-audit --strict` und `uv run pytest -q`; die Tabelle listet ergänzende Pflichtläufe.

| Pflichtlauf | Zweck |
| ------------ | ----- |
| `uv run make doctor` | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline freundlich) aus und verifiziert `/downloads` & `/music` via Schreib-/Lesetest. |
| `uv run make ui-guard` | Verhindert Platzhalterstrings in Templates, blockiert `/api/...` HTMX-Aufrufe und stellt sicher, dass statische Assets vorhanden sind. |
| `uv run make ui-smoke` | Startet die App lokal und ruft `/live`, `/ui` sowie UI-Fragmente ab; schlägt fehl, wenn HTML-Antworten Platzhalter enthalten oder kein `text/html` liefern. |
| `uv run pip-audit --strict` | `scripts/dev/pip_audit.sh` auditiert die im Lockfile fixierten Abhängigkeiten ohne Make-Wrapper; Standard-Gate. |
| `uv run pytest -q` | `scripts/dev/test_py.sh` (`uv run make test`) führt die Test-Suite schlank aus; Standard-Gate. |
| `uv run make all` | Führt Formatierung, Lint, Dependency-Sync, Backend-Tests, Supply-Guard und Smoke-Test aus. |
| `uv run make release-check` | Ruft `scripts/dev/release_check.py` auf, kombiniert `uv run make all`, `uv run make docs-verify`, `uv run make pip-audit` sowie einen abschließenden `uv run make ui-smoke`, schreibt strukturierte Logs und stoppt beim ersten Fehler. Optional via `--dry-run` oder `RELEASE_CHECK_COMMANDS` parametrisierbar. |
| `uv run make image-lsio` / `uv run make smoke-lsio` | Erstellt das LinuxServer.io-Image (`docker/Dockerfile.lsio`) und prüft es mit einem Healthcheck- und Datenbank-Bootstrap-Lauf. |
| `pre-commit run --all-files` | Spiegelt alle Commit-Hooks (`ruff-format`, `ruff`, lokale Skripte). |
| `pre-commit run --hook-stage push` | Führt `scripts/dev/test_py.sh` vor dem Push aus. |

## Branch Protection & Evidence

- Branch-Protection-Regeln verlangen einen erfolgreichen `release-check`-Status; zusätzliche Checks (z. B. `docker-image`) können je nach Repository-Einstellung erforderlich sein.
- Der Workflow [`release-check`](../../.github/workflows/release-check.yml) läuft automatisch für Branches `release/**` sowie Tags `v*`, führt `uv run make release-check` inklusive `uv run make docs-verify`, `uv run make pip-audit` und UI-Smoke-Test aus und validiert anschließend den Packaging-Pipeline-Run via `uv run make package-verify`.
- Die Workflow-Logs werden als Artefakt `release-check-logs` gespeichert und enthalten die Datei `reports/release-check/release-check.log` als revisionssicheren Nachweis. Zusätzlich archiviert der Workflow das Artefakt `release-packaging-artifacts` mit dem Inhalt des Verzeichnisses `dist/` für eine spätere manuelle Prüfung.
- Maintainer prüfen die GitHub-Actions-Protokolle (`release-check` und ggf. `docker-image`) sowie die angehängten Logs der lokalen Pflichtläufe, bevor sie freigeben.
- PRs ohne Wiring-/Removal-Report oder ohne Logs der Pflichtläufe dürfen nicht gemergt werden.
- Speichere relevante Terminalausgaben in `reports/` (aus dem `.gitignore`) oder im PR-Body.

## Pre-commit Hooks

Installiere die Hooks nach einem `uv sync --frozen` mit:

```bash
uv tool install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
uv run pre-commit run --all-files
uv run pre-commit run --hook-stage push
```

- Lokale Hooks rufen `scripts/dev/fmt.sh` und `scripts/dev/dep_sync_py.sh` auf.
- Der Pre-Push-Hook startet `scripts/dev/test_py.sh`. Bei Fehlern werden Pushes abgebrochen.

## Manuelle Nightly-/Security-Checks

- `uv run make release-check` führt `pip-audit` bereits für alle im `uv.lock` fixierten Abhängigkeiten aus. Dokumentiere erkannte
  Schwachstellen direkt im PR, falls der Lauf fehlschlägt.
- Generiere auf Wunsch SBOMs über `uv tool install cyclonedx-bom` und dokumentiere externe Bezugsquellen der Python-Abhängigkeiten.

## Release Checklist

1. Versionierung & CHANGELOG aktualisieren.
2. `uv run make release-check` (inkl. `uv run make docs-verify`, `uv run make pip-audit` und UI-Smoketest) und optionale Security-Scans erneut ausführen.
3. Packaging-Workflow nachvollziehen:
   - Lokal `uv run make package-verify` ausführen (führt `pip install .`, `pip wheel . -w dist/` und `python -m build` sequenziell mit Cleanups zwischen den Schritten aus).
   - Alternativ die CI-Artefakte (`release-packaging-artifacts`) des Workflows [`release-check`](../../.github/workflows/release-check.yml) prüfen, um den letzten erfolgreichen Build zu bestätigen.
4. Releases/Tarballs manuell hochladen und Release Notes verfassen (Highlights, Breaking Changes, Rollback-Plan).

## Operational Ownership

- **Primary Owner:** Internes Harmony Operations Team (siehe privates Ownership-Register).
- **Bereitschaft:** On-Call-Rotation laut internem Ops-Kalender; benachrichtigen Sie die diensthabende Person über Hotline oder On-Call-Tool.
- **Koordination:** Bei ausbleibender Rückmeldung eskaliert die Bereitschaft an die Plattform-Leitung über den Incident-Bridge-Anruf (`ops-bridge`).
- **Dokumentation:** Alle Wartungsarbeiten und Eskalationen werden im privaten Ops-Journal protokolliert; es existiert kein öffentlicher Kontaktkanal.
- **Monitoring:** Stichprobenartig die ersten PRs nach Tooling-Updates prüfen, damit Laufzeiten und Anforderungen realistisch bleiben.
