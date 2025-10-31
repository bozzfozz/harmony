# Lokaler Workflow ohne zentrale Build-Pipeline

Harmony verlässt sich weiterhin auf nachvollziehbare lokale Gates. Ergänzend prüft der GitHub-Actions-Workflow [`release-check`](../../.github/workflows/release-check.yml) alle Release-Branches, Release-Tags und manuellen Dispatches mit denselben Kern-Gates; das manuell ausgelöste [`docker-image`](../../.github/workflows/docker-image.yml) wiederholt den Gate-Lauf, bevor Container-Builds erstellt werden.

## Pflichtkommandos

Führe vor den Gates einmal `uv sync --frozen` aus und starte anschließende
Make-Targets konsequent via `uv run make <target>`, damit alle Schritte im durch
`uv.lock` definierten Environment laufen. Der Standard-Gate-Lauf besteht aus
`uv run pip-audit --strict` und `uv run pytest -q`; die Tabelle listet zusätzliche
Targets und Hilfsskripte für umfassendere Prüfungen.

| Kommando                        | Script                              | Zweck |
| -------------------------------- | ----------------------------------- | ----- |
| `uv run make doctor`             | `scripts/dev/doctor.sh`             | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline-tolerant) aus und verifiziert `/downloads` & `/music` mit Schreib-/Lesetest. |
| `uv run make ui-guard`           | `scripts/dev/ui_guard.sh`           | Durchsucht UI-Templates und statische Assets nach Platzhaltern, verbietet direkte HTMX-Aufrufe auf `/api/...` und prüft, dass die verpflichtenden Dateien unter `app/ui/static/` existieren. |
| `uv run make ui-smoke`           | `scripts/dev/ui_smoke_local.sh`     | Startet die FastAPI-App lokal, ruft `/live`, `/ui` sowie exemplarische Fragmente auf und bricht ab, wenn die HTML-Antworten Platzhalter enthalten oder kein `text/html` liefern. |
| `uv run make fmt`                | `scripts/dev/fmt.sh`                | Führt `ruff format` und Import-Sortierung (`ruff check --select I --fix`) aus. |
| `uv run make lint`               | `scripts/dev/lint_py.sh`            | Führt `ruff check --output-format=concise .` und `mypy app tests --config-file mypy.ini` aus. |
| `uv run make dep-sync`           | `scripts/dev/dep_sync_py.sh`        | Prüft Python-Abhängigkeiten auf fehlende oder ungenutzte Pakete. |
| `uv run pip-audit --strict`      | `scripts/dev/pip_audit.sh`          | Auditiert die im Lockfile fixierten Abhängigkeiten ohne Make-Wrapper; Standard-Gate. |
| `uv run pytest -q`               | `scripts/dev/test_py.sh` (`uv run make test`) | Erstellt eine SQLite-Testdatenbank unter `.tmp/test.db` und führt die Test-Suite schlank aus. Benötigt Node.js ≥ 18 für den UI-Bootstrap-Test [`tests/ui/test_ui_bootstrap.py`](../../tests/ui/test_ui_bootstrap.py). |
| `uv run make be-verify`          | —                                   | Alias für `make test`; dient als explizites Backend-Gate im `make all`-Lauf. |
| `uv run make supply-guard`       | `scripts/dev/supply_guard.sh`       | Prüft auf versehentlich eingecheckte Node-Build-Artefakte. |
| `uv run make smoke`              | `scripts/dev/smoke_unified.sh`      | Startet `uvicorn app.main:app`, pingt bis zu 60 Sekunden `http://127.0.0.1:${APP_PORT}${SMOKE_PATH}` und beendet den Prozess kontrolliert; führt anschließend einen optionalen Readiness-Ping gegen `/api/health/ready?verbose=1` aus (`SMOKE_READY_CHECK=warn` standard, `strict` erzwingt einen Fehler). Optional wird ein vorhandenes Unified-Docker-Image geprüft. |
| `uv run make image-lsio`         | —                                   | Baut das LinuxServer.io-kompatible Image `lscr.io/linuxserver/harmony:latest` anhand von `docker/Dockerfile.lsio`. |
| `uv run make smoke-lsio`         | `scripts/dev/smoke_lsio.sh`         | Startet das LSIO-Image in einem temporären Container, wartet bis zu 60 Sekunden auf einen erfolgreichen Healthcheck gegen `http://127.0.0.1:${HARMONY_LSIO_SMOKE_PORT:-18080}/api/health/ready` und prüft anschließend, dass `/config/harmony.db` im Container sowie auf dem gemounteten Host-Pfad existiert. |
| `uv run make all`                | —                                   | Kombiniert `fmt lint dep-sync be-verify supply-guard smoke` in fester Reihenfolge (der `lint`-Schritt umfasst Ruff und MyPy). |
| `uv run make release-check`      | `scripts/dev/release_check.py`      | Führt `uv run make all`, `uv run make docs-verify`, `uv run make pip-audit` und `uv run make ui-smoke` aus, protokolliert strukturierte JSON-Logs, stoppt beim ersten Fehler und unterstützt `--dry-run` sowie `RELEASE_CHECK_COMMANDS` für CI-Overrides. |

**Hinweis:** MyPy ist jetzt ein Pflicht-Gate innerhalb von `uv run make lint`. Schlägt die statische Typprüfung fehl oder fehlt das Tooling, wird der gesamte Lauf (und damit auch `uv run make all` bzw. `uv run make release-check`) mit einem Fehler abgebrochen.

**Zusatzhinweis:** `uv run make pip-audit` verwendet `uvx pip-audit` und benötigt Internetzugang, damit die Sicherheitsprüfung erfolgreich abgeschlossen werden kann.

### Voraussetzungen für den UI-Smoketest

Damit `uv run make ui-smoke` (oder der in `uv run make release-check` integrierte Lauf) zuverlässig grün wird, müssen lokal folgende Bedingungen erfüllt sein:

- **Python-Abhängigkeiten installiert:** `uvicorn` und `httpx` stammen aus den Backend-Requirements. Installiere sie über `uv sync --frozen`.
- **Freier API-Port:** Der Test startet `uvicorn` auf dem per `APP_PORT` (Standard: `8080`) aus `app.config` ermittelten Port. Stelle sicher, dass kein anderes Programm auf diesem Port lauscht oder setze `APP_PORT` vorher auf einen freien Port.
- **Schreibrechte im Repository:** Das Skript legt Log- und Daten-Dateien unter `.tmp/` an (`ui-smoke.log`, `ui-smoke.db`, Downloads/Music-Verzeichnisse). Für schreibgeschützte Mounts oder temporäre Dateisysteme muss ein alternativer Speicherort per `TMPDIR`/`DOWNLOADS_DIR`/`MUSIC_DIR` konfiguriert werden.
- **Loopback-Erreichbarkeit:** Der Test ruft das UI über `http://127.0.0.1:${APP_PORT}` auf. Lokale Firewalls oder Container-Netzwerkregeln dürfen Verbindungen zum Loopback-Interface nicht blockieren.
- **Soulseek-Proxy konfigurieren:** Ohne konfigurierten `SLSKD_API_KEY` bricht der Backend-Start vor dem Smoketest ab. Setze für lokale Läufe einen Dummy-Wert (z. B. `ui-smoke-key`), falls kein echtes SoulseekD-Backend erreichbar ist.

## GitHub Actions `release-check`

Der Workflow sichert Release-Branches, Release-Tags und manuelle Dispatches mit denselben Gates ab, die lokal verpflichtend sind:

- Installiert Abhängigkeiten und führt `uv run make release-check` aus. Das Target kombiniert `uv run make all` (Formatierung, Linting, Dependency-Sync, Tests, Supply-Guard, Smoke), `uv run make docs-verify`, `uv run make pip-audit` und `uv run make ui-smoke`.
- Bricht beim ersten Fehler ab, schreibt strukturierte Logs nach `reports/release-check/release-check.log` und stellt per `git diff --exit-code` sicher, dass der Lauf keine Artefakte hinterlässt.
- Führt anschließend `uv run make package-verify` aus, um Installation, Wheel-Build und `python -m build` zu validieren.

Die hochgeladenen Artefakte (`release-check-logs`, `release-packaging-artifacts`) dokumentieren die Gate-Läufe und erleichtern Reviews. Beitragsende sollten vor jedem Push dieselben Targets lokal ausführen und die erzeugten Logs im PR referenzieren.

Das manuell auslösbare [`docker-image`](../../.github/workflows/docker-image.yml) nutzt denselben `uv run make release-check`-Gate-Lauf als Vorbedingung für Container-Builds und kann optional einen Container-Smoketest starten, bevor Images gepusht werden.

Der Readiness-Self-Check überwacht weiterhin alle Pflicht-Templates sowie `app/ui/static/css/app.css`, `app/ui/static/js/htmx.min.js` und `app/ui/static/icons.svg`. Fehlt eines dieser Artefakte, melden `/api/health/ready`, `/api/system/ready` und `/api/system/status` einen degradierten Zustand.

## Ablauf vor jedem Merge

1. **Tooling prüfen:** `uv run make doctor`
2. **UI-Guards laufen lassen:** `uv run make ui-guard`
3. **UI-Smoketest:** `uv run make ui-smoke`
4. **Hooks installieren:**
   ```bash
   pre-commit install
   pre-commit install --hook-type pre-push
   uv run pre-commit run --all-files
   uv run pre-commit run --hook-stage push
   ```
   Die konfigurierten Hooks prüfen aktuell ausschließlich die Python-Toolchain und das Supply-Chain-Guardrail:
   - `ruff-format` und `ruff` laufen direkt aus dem offiziellen Repository.
   - `scripts/dev/fmt.sh` und `scripts/dev/dep_sync_py.sh` stellen Formatierung sowie Python-Abhängigkeiten sicher.
   - `scripts/dev/supply_guard.sh` verhindert eingecheckte Frontend-Build-Artefakte.
   - `scripts/dev/test_py.sh` wird als Pre-Push-Hook ausgeführt und deckt den Pytest-Lauf ab.
   Ein dedizierter JavaScript- oder Frontend-Verify-Hook ist derzeit nicht mehr aktiv.
5. **Standard-Gate:**
   ```bash
   uv run pip-audit --strict
   uv run pytest -q
   ```
   Ergänzend kannst du `uv run make all` oder `uv run make release-check`
   ausführen, wenn du den aggregierten Workflow bevorzugst.
6. **Evidence sichern:** Bewahre die wichtigsten Log-Auszüge pro Schritt auf (siehe PR-Checkliste).
7. **Frontend-/Backend-Wiring dokumentieren:** Erstelle einen Wiring-Report (neue Routen, Worker, Registrierungen) sowie einen Removal-Report für gelöschte Artefakte.

## Troubleshooting

### `uv run make doctor`
- **Fehlende Tools:** Installiere Python ≥ 3.10, Ruff und Pytest.
- **Security-Audit offline:** Ohne Internetzugang meldet `pip-audit` ein WARN und der Lauf bleibt grün.
- **Directory-Probleme:** Das Skript legt `DOWNLOADS_DIR`/`MUSIC_DIR` automatisch an. Prüfe Mounts und Berechtigungen, falls der Schreib-/Lesetest scheitert.
- **Optionale Requirement-Guards:** Setze `DOCTOR_PIP_REQS=1`, wenn `pip-missing-reqs`/`pip-extra-reqs` zwingend geprüft werden sollen.

### `uv run make dep-sync`
- **Missing Dependencies:** Aktualisiere `pyproject.toml`/`uv.lock` und wiederhole den Lauf.
- **Unused Dependencies:** Entferne nicht mehr benötigte Pakete oder markiere sie als bewusst benötigt (z. B. durch tatsächliche Nutzung in Code/Tests).

### `uv run make supply-guard`
- **Node-Artefakte:** Entferne versehentlich eingecheckte Node-Lockfiles oder Toolchain-Relikte (z. B. `package-lock.json`, `.nvmrc`).

### `uv run make smoke`
- **Server startet nicht:** Kontrolliere `.tmp/smoke.log` (wird automatisch ausgegeben) und stelle sicher, dass `DATABASE_URL` auf eine schreibbare SQLite-Datei zeigt.
- **Port belegt:** Setze `APP_PORT=<frei>` (z. B. via `.env`) und starte den Smoke-Test erneut.
- **Legacy-Aliasse normalisiert:** Werte in `PORT`, `UVICORN_PORT` oder `WEB_PORT` werden als Fallback genutzt, wenn `APP_PORT` fehlt. Setze `APP_PORT` explizit, damit der Smoke-Test ohne Warnungen durchläuft.
- **Docker-Sektion:** Setze `SMOKE_UNIFIED_IMAGE` auf einen vorhandenen Tag, wenn du die optionale Container-Prüfung ausführen möchtest. Bei Fehlern werden automatisch `docker logs`, `docker exec … ps`, `ss/netstat` sowie die relevanten Port-Variablen ausgegeben.

## Nachweise im PR

- Output von `uv run make doctor` (Kurzfassung: `All doctor checks passed.`)
- Konsolenausschnitte jedes `uv run make all`-Schrittes (mindestens die letzten 5–10 Zeilen pro Kommando).
- Aktualisierte Wiring-/Removal-Reports im PR-Body.
- Hinweise auf besondere Overrides (z. B. alternative Ports, deaktivierte Worker) in den PR-Notizen.
- **UI-Guard:** Verweist die Fehlermeldung auf einen Platzhalter oder `hx-*` Aufruf? Entferne den entsprechenden String aus den Templates. Stelle sicher, dass `app/ui/static/css/app.css`, `app/ui/static/js/htmx.min.js` und `app/ui/static/icons.svg` nicht leer sind.
- **UI-Smoketest:** Schlägt der Test wegen fehlender HTML-Content-Types oder Platzhaltertext fehl, kontrolliere die gerenderten Templates und starte den Test erneut. Bei Startproblemen zeigt `.tmp/ui-smoke.log` die Backend-Logs.
