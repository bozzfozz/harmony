# Lokaler Workflow ohne zentrale Build-Pipeline

Harmony verlässt sich weiterhin auf nachvollziehbare lokale Gates. Ergänzend prüft der GitHub-Actions-Workflow [`backend-ci`](../../.github/workflows/ci.yml) jede Pull-Request sowie Pushes auf `main` mit denselben Kern-Gates, damit Beitragsende ihre lokalen Logs direkt mit den CI-Ergebnissen abgleichen können.

## Pflichtkommandos

| Kommando                  | Script                              | Zweck |
| ------------------------- | ----------------------------------- | ----- |
| `make doctor`             | `scripts/dev/doctor.sh`             | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline-tolerant) aus und verifiziert `/data/downloads` & `/data/music` mit Schreib-/Lesetest. |
| `make ui-guard`           | `scripts/dev/ui_guard.sh`           | Durchsucht UI-Templates und statische Assets nach Platzhaltern, verbietet direkte HTMX-Aufrufe auf `/api/...` und prüft, dass die verpflichtenden Dateien unter `app/ui/static/` existieren. |
| `make ui-smoke`           | `scripts/dev/ui_smoke_local.sh`     | Startet die FastAPI-App lokal, ruft `/live`, `/ui` sowie exemplarische Fragmente auf und bricht ab, wenn die HTML-Antworten Platzhalter enthalten oder kein `text/html` liefern. |
| `make fmt`                | `scripts/dev/fmt.sh`                | Führt `ruff format` und Import-Sortierung (`ruff check --select I --fix`) aus. |
| `make lint`               | `scripts/dev/lint_py.sh`            | Führt `ruff check --output-format=concise .` und `mypy app tests --config-file mypy.ini` aus. |
| `make dep-sync`           | `scripts/dev/dep_sync_py.sh`        | Prüft Python-Abhängigkeiten auf fehlende oder ungenutzte Pakete. |
| `make test`               | `scripts/dev/test_py.sh`            | Erstellt eine SQLite-Testdatenbank unter `.tmp/test.db` und startet `pytest -q`. |
| `make be-verify`          | —                                   | Alias für `make test`; dient als explizites Backend-Gate im `make all`-Lauf. |
| `make supply-guard`       | `scripts/dev/supply_guard.sh`       | Prüft auf versehentlich eingecheckte Node-Build-Artefakte. |
| `make smoke`              | `scripts/dev/smoke_unified.sh`      | Startet `uvicorn app.main:app`, pingt bis zu 60 Sekunden `http://127.0.0.1:${APP_PORT}${SMOKE_PATH}` und beendet den Prozess kontrolliert; optional wird ein vorhandenes Unified-Docker-Image geprüft. |
| `make all`                | —                                   | Kombiniert `fmt lint dep-sync be-verify supply-guard smoke` in fester Reihenfolge (der `lint`-Schritt umfasst Ruff und MyPy). |

**Hinweis:** MyPy ist jetzt ein Pflicht-Gate innerhalb von `make lint`. Schlägt die statische Typprüfung fehl oder fehlt das Tooling, wird der gesamte Lauf (und damit auch `make all`) mit einem Fehler abgebrochen.

## GitHub Actions `backend-ci`

Der Workflow stellt sicher, dass jede Änderung im Repository die wichtigsten Backend-Gates durchläuft:

- **Format-Check:** `make fmt` läuft im Check-Modus (`git diff --exit-code` beendet den Lauf bei Formatierungsdrift).
- **Linting & Typen:** `make lint` deckt Ruff und MyPy ab.
- **Tests mit Coverage:** `make test` läuft mit `PYTEST_ADDOPTS=--cov=app --cov-report=xml --junitxml=...` und erzeugt `reports/ci/coverage.xml` sowie `reports/ci/pytest-junit.xml` für Artefakt-Uploads.
- **Smoke-Test:** `make smoke` startet den FastAPI-Server inklusive Health-Ping.

Die hochgeladenen Artefakte (`pytest-junit`, `coverage-xml`) erleichtern Reviews und dokumentieren fehlgeschlagene Läufe. Beitragsende sollten vor jedem Push dieselben Targets lokal ausführen und die erzeugten Logs im PR referenzieren.

Der Readiness-Self-Check überwacht zusätzlich alle Pflicht-Templates sowie `app/ui/static/css/app.css`, `app/ui/static/js/htmx.min.js` und `app/ui/static/icons.svg`. Fehlt eines dieser Artefakte, melden `/api/health/ready`, `/api/system/ready` und `/api/system/status` einen degradierten Zustand.

## Ablauf vor jedem Merge

1. **Tooling prüfen:** `make doctor`
2. **UI-Guards laufen lassen:** `make ui-guard`
3. **UI-Smoketest:** `make ui-smoke`
4. **Hooks installieren:**
   ```bash
   pre-commit install
   pre-commit install --hook-type pre-push
   pre-commit run --all-files
   ```
   Die konfigurierten Hooks prüfen aktuell ausschließlich die Python-Toolchain und das Supply-Chain-Guardrail:
   - `ruff-format` und `ruff` laufen direkt aus dem offiziellen Repository.
   - `scripts/dev/fmt.sh` und `scripts/dev/dep_sync_py.sh` stellen Formatierung sowie Python-Abhängigkeiten sicher.
   - `scripts/dev/supply_guard.sh` verhindert eingecheckte Frontend-Build-Artefakte.
   - `scripts/dev/test_py.sh` wird als Pre-Push-Hook ausgeführt und deckt den Pytest-Lauf ab.
   Ein dedizierter JavaScript- oder Frontend-Verify-Hook ist derzeit nicht mehr aktiv.
5. **Kompletter Gate-Lauf:** `make all`
6. **Evidence sichern:** Bewahre die wichtigsten Log-Auszüge pro Schritt auf (siehe PR-Checkliste).
7. **Frontend-/Backend-Wiring dokumentieren:** Erstelle einen Wiring-Report (neue Routen, Worker, Registrierungen) sowie einen Removal-Report für gelöschte Artefakte.

## Troubleshooting

### `make doctor`
- **Fehlende Tools:** Installiere Python ≥ 3.10, Ruff und Pytest.
- **Security-Audit offline:** Ohne Internetzugang meldet `pip-audit` ein WARN und der Lauf bleibt grün.
- **Directory-Probleme:** Das Skript legt `DOWNLOADS_DIR`/`MUSIC_DIR` automatisch an. Prüfe Mounts und Berechtigungen, falls der Schreib-/Lesetest scheitert.
- **Optionale Requirement-Guards:** Setze `DOCTOR_PIP_REQS=1`, wenn `pip-missing-reqs`/`pip-extra-reqs` zwingend geprüft werden sollen.

### `make dep-sync`
- **Missing Dependencies:** Passe `requirements*.txt` an und wiederhole den Lauf.
- **Unused Dependencies:** Entferne nicht mehr benötigte Pakete oder markiere sie als bewusst benötigt (z. B. durch tatsächliche Nutzung in Code/Tests).

### `make supply-guard`
- **Node-Artefakte:** Entferne versehentlich eingecheckte Node-Lockfiles oder Toolchain-Relikte (z. B. `package-lock.json`, `.nvmrc`).

### `make smoke`
- **Server startet nicht:** Kontrolliere `.tmp/smoke.log` (wird automatisch ausgegeben) und stelle sicher, dass `DATABASE_URL` auf eine schreibbare SQLite-Datei zeigt.
- **Port belegt:** Setze `APP_PORT=<frei>` (z. B. via `.env`) und starte den Smoke-Test erneut.
- **Legacy-Aliasse normalisiert:** Werte in `PORT`, `UVICORN_PORT` oder `WEB_PORT` werden als Fallback genutzt, wenn `APP_PORT` fehlt. Setze `APP_PORT` explizit, damit der Smoke-Test ohne Warnungen durchläuft.
- **Docker-Sektion:** Setze `SMOKE_UNIFIED_IMAGE` auf einen vorhandenen Tag, wenn du die optionale Container-Prüfung ausführen möchtest. Bei Fehlern werden automatisch `docker logs`, `docker exec … ps`, `ss/netstat` sowie die relevanten Port-Variablen ausgegeben.

## Nachweise im PR

- Output von `make doctor` (Kurzfassung: `All doctor checks passed.`)
- Konsolenausschnitte jedes `make all`-Schrittes (mindestens die letzten 5–10 Zeilen pro Kommando).
- Aktualisierte Wiring-/Removal-Reports im PR-Body.
- Hinweise auf besondere Overrides (z. B. alternative Ports, deaktivierte Worker) in den PR-Notizen.
- **UI-Guard:** Verweist die Fehlermeldung auf einen Platzhalter oder `hx-*` Aufruf? Entferne den entsprechenden String aus den Templates. Stelle sicher, dass `app/ui/static/css/app.css`, `app/ui/static/js/htmx.min.js` und `app/ui/static/icons.svg` nicht leer sind.
- **UI-Smoketest:** Schlägt der Test wegen fehlender HTML-Content-Types oder Platzhaltertext fehl, kontrolliere die gerenderten Templates und starte den Test erneut. Bei Startproblemen zeigt `.tmp/ui-smoke.log` die Backend-Logs.
