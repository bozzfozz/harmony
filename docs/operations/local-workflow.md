# Lokaler Workflow ohne zentrale Build-Pipeline

Harmony verlässt sich vollständig auf lokale Gates. Alle Merge-Entscheidungen basieren auf nachvollziehbaren Logs der folgenden Skripte und Makefile-Targets.

## Pflichtkommandos

| Kommando                  | Script                              | Zweck |
| ------------------------- | ----------------------------------- | ----- |
| `make doctor`             | `scripts/dev/doctor.sh`             | Prüft Tooling (Python, Ruff, Pytest), führt `pip check`/`pip-audit` (offline-tolerant) aus und verifiziert `/data/downloads` & `/data/music` mit Schreib-/Lesetest. |
| `make fmt`                | `scripts/dev/fmt.sh`                | Führt `ruff format` und Import-Sortierung (`ruff check --select I --fix`) aus. |
| `make lint`               | `scripts/dev/lint_py.sh`            | Ruft `ruff check --output-format=concise .` auf. |
| `make dep-sync`           | `scripts/dev/dep_sync_py.sh`        | Prüft Python-Abhängigkeiten auf fehlende oder ungenutzte Pakete. |
| `make test`               | `scripts/dev/test_py.sh`            | Erstellt eine SQLite-Testdatenbank unter `.tmp/test.db` und startet `pytest -q`. |
| `make be-verify`          | —                                   | Alias für `make test`; dient als explizites Backend-Gate im `make all`-Lauf. |
| `make supply-guard`       | `scripts/dev/supply_guard.sh`       | Prüft auf versehentlich eingecheckte Node-Build-Artefakte. |
| `make smoke`              | `scripts/dev/smoke_unified.sh`      | Startet `uvicorn app.main:app`, pingt bis zu 60 Sekunden `http://127.0.0.1:${APP_PORT}${SMOKE_PATH}` und beendet den Prozess kontrolliert; optional wird ein vorhandenes Unified-Docker-Image geprüft. |
| `make all`                | —                                   | Kombiniert `fmt lint dep-sync be-verify supply-guard smoke` in fester Reihenfolge. |

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
