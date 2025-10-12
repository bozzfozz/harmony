# Lokaler Workflow ohne zentrale Build-Pipeline

Harmony verlässt sich vollständig auf lokale Gates. Alle Merge-Entscheidungen basieren auf nachvollziehbaren Logs der folgenden Skripte und Makefile-Targets.

## Pflichtkommandos

| Kommando            | Script                         | Zweck |
| ------------------- | ------------------------------ | ----- |
| `make doctor`       | `scripts/dev/doctor.sh`        | Prüft Tooling (Python, Ruff, Pytest, Node/npm, pip-check-reqs) sowie Schreibrechte auf `/data/downloads` und `/data/music`.
| `make fmt`          | `scripts/dev/fmt.sh`           | Führt `ruff format` und Import-Sortierung (`ruff check --select I --fix`) aus.
| `make lint`         | `scripts/dev/lint_py.sh`       | Ruft `ruff check --output-format=concise .` auf.
| `make dep-sync`     | `dep_sync_py.sh` + `dep_sync_js.sh` | Prüft Python- und npm-Abhängigkeiten auf fehlende oder ungenutzte Pakete.
| `make test`         | `scripts/dev/test_py.sh`       | Erstellt eine SQLite-Testdatenbank unter `.tmp/test.db` und startet `pytest -q`.
| `make fe-build`     | `scripts/dev/build_fe.sh`      | Installiert npm-Abhängigkeiten (`npm ci`) und baut das Frontend (`npm run build`).
| `make smoke`        | `scripts/dev/smoke_unified.sh` | Startet `uvicorn app.main:app`, pingt `/api/health/live` und beendet den Prozess kontrolliert; optional wird ein vorhandenes Unified-Docker-Image geprüft.
| `make all`          | —                              | Kombiniert `fmt lint dep-sync test fe-build smoke` in fester Reihenfolge.

## Ablauf vor jedem Merge

1. **Tooling prüfen:** `make doctor`
2. **Hooks installieren:**
   ```bash
   pre-commit install
   pre-commit install --hook-type pre-push
   pre-commit run --all-files
   ```
3. **Kompletter Gate-Lauf:** `make all`
4. **Evidence sichern:** Bewahre die wichtigsten Log-Auszüge pro Schritt auf (siehe PR-Checkliste).
5. **Frontend-/Backend-Wiring dokumentieren:** Erstelle einen Wiring-Report (neue Routen, Worker, Registrierungen) sowie einen Removal-Report für gelöschte Artefakte.

## Troubleshooting

### `make doctor`
- **Fehlende Tools:** Installiere Python ≥ 3.10, Ruff, Pytest sowie Node.js inklusive npm.
- **pip-check-reqs fehlt:** `pip install pip-check-reqs`
- **Write-Permissions:** Erstelle `/data/downloads` und `/data/music` und setze Schreibrechte für deinen Benutzer.

### `make fmt` / `make lint`
- **Persistente Drift:** Führe `scripts/dev/fmt.sh` erneut aus. Bewusst ungenutzte Importe mit `# noqa` + Begründung versehen.
- **Unbekannter Fehlercode:** Aktualisiere Ruff (`pip install -U ruff`).

### `make dep-sync`
- **Missing Dependencies:** Passe `requirements*.txt` oder `package.json`/`package-lock.json` an und wiederhole den Lauf.
- **Unused Dependencies:** Entferne nicht mehr benötigte Pakete oder markiere sie als bewusst benötigt (z. B. durch tatsächliche Nutzung in Code/Tests).

### `make test`
- **SQLite-Lock:** Lösche `.tmp/test.db` und wiederhole den Lauf; stelle sicher, dass keine parallelen Server laufen.
- **Flaky Tests:** Prüfe Logs im Pytest-Output und halte reproduzierbare Schritte für den PR fest.

### `make fe-build`
- **npm-Cache-Probleme:** Setze `NPM_CONFIG_CACHE="$(mktemp -d)"` und wiederhole `npm ci`.
- **TypeScript-Fehler:** Richte dich nach dem Terminal-Output (`tsc`/Vite) und committe die notwendigen Code-Anpassungen.

### `make smoke`
- **Server startet nicht:** Kontrolliere `.tmp/smoke.log` und stelle sicher, dass `DATABASE_URL` auf eine schreibbare SQLite-Datei zeigt.
- **Port belegt:** Setze `SMOKE_PORT=<frei>` und starte den Smoke-Test erneut.
- **Docker-Sektion:** Setze `SMOKE_UNIFIED_IMAGE` auf einen vorhandenen Tag, wenn du die optionale Container-Prüfung ausführen möchtest.

## Nachweise im PR

- Output von `make doctor` (Kurzfassung: `All doctor checks passed.`)
- Konsolenausschnitte jedes `make all`-Schrittes (mindestens die letzten 5–10 Zeilen pro Kommando).
- Aktualisierte Wiring-/Removal-Reports im PR-Body.
- Hinweise auf besondere Overrides (z. B. alternative Ports, deaktivierte Worker) in den PR-Notizen.
