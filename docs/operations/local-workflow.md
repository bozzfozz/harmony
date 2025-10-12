# Lokaler Workflow ohne zentrale Build-Pipeline

Harmony verlässt sich vollständig auf lokale Gates. Alle Merge-Entscheidungen basieren auf nachvollziehbaren Logs der folgenden Skripte und Makefile-Targets.

## Pflichtkommandos

| Kommando                  | Script                              | Zweck |
| ------------------------- | ----------------------------------- | ----- |
| `make doctor`             | `scripts/dev/doctor.sh`             | Prüft Tooling (Python, Ruff, Pytest, pip-check-reqs) sowie Schreibrechte auf `/data/downloads` und `/data/music`. |
| `make fmt`                | `scripts/dev/fmt.sh`                | Führt `ruff format` und Import-Sortierung (`ruff check --select I --fix`) aus. |
| `make lint`               | `scripts/dev/lint_py.sh`            | Ruft `ruff check --output-format=concise .` auf. |
| `make dep-sync`           | `scripts/dev/dep_sync_py.sh`        | Prüft Python-Abhängigkeiten auf fehlende oder ungenutzte Pakete. |
| `make test`               | `scripts/dev/test_py.sh`            | Erstellt eine SQLite-Testdatenbank unter `.tmp/test.db` und startet `pytest -q`. |
| `make be-verify`          | —                                   | Alias für `make test`; dient als explizites Backend-Gate im `make all`-Lauf. |
| `make supply-guard`       | `scripts/dev/supply_guard.sh`       | Stellt sicher, dass keine Paketmanager-Artefakte vorhanden sind und Import-Maps gepinnt bleiben. |
| `make vendor-frontend`    | `scripts/dev/vendor_frontend.sh`    | Lädt CDN-Module in `frontend/static/vendor/` und rewritet Import-Maps für Offline-Betrieb. |
| `make vendor-frontend-reset` | `scripts/dev/vendor_frontend.sh --reset` | Entfernt lokale Vendor-Dateien und stellt den CDN-Modus wieder her. |
| `make smoke`              | `scripts/dev/smoke_unified.sh`      | Startet `uvicorn app.main:app`, pingt standardmäßig `/live` und beendet den Prozess kontrolliert; optional wird ein vorhandenes Unified-Docker-Image geprüft. |
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
4. **Optionaler Offline-Test:** `make vendor-frontend` ausführen, Applikation ohne Internetzugang testen und anschließend via `make vendor-frontend-reset` zurück in den CDN-Modus wechseln.
5. **Evidence sichern:** Bewahre die wichtigsten Log-Auszüge pro Schritt auf (siehe PR-Checkliste).
6. **Frontend-/Backend-Wiring dokumentieren:** Erstelle einen Wiring-Report (neue Routen, Worker, Registrierungen) sowie einen Removal-Report für gelöschte Artefakte.

## Troubleshooting

### `make doctor`
- **Fehlende Tools:** Installiere Python ≥ 3.10, Ruff, Pytest sowie `pip-check-reqs`.
- **pip-check-reqs fehlt:** `pip install pip-check-reqs`
- **Write-Permissions:** Erstelle `/data/downloads` und `/data/music` und setze Schreibrechte für deinen Benutzer.

### `make dep-sync`
- **Missing Dependencies:** Passe `requirements*.txt` an und wiederhole den Lauf.
- **Unused Dependencies:** Entferne nicht mehr benötigte Pakete oder markiere sie als bewusst benötigt (z. B. durch tatsächliche Nutzung in Code/Tests).

### `make supply-guard`
- **Import-Map ungepinnt:** Prüfe `frontend/importmap.json`, setze feste Versions-Pins (`@x.y.z`) und wiederhole den Lauf.
- **Verbotene Artefakte:** Entferne `package-lock.json`, `.npmrc`, `.nvmrc` oder ähnliche Dateien. Das Frontend arbeitet vollständig ohne Paketmanager.

### `make vendor-frontend`
- **Download-Fehler:** Stelle sicher, dass die CDN-Quellen erreichbar sind. Bei Bedarf Proxy konfigurieren oder Module manuell in `frontend/static/vendor/` legen.
- **Unerwünschte Änderungen:** Nutze `make vendor-frontend-reset`, um den Ausgangszustand wiederherzustellen.

### `make smoke`
- **Server startet nicht:** Kontrolliere `.tmp/smoke.log` und stelle sicher, dass `DATABASE_URL` auf eine schreibbare SQLite-Datei zeigt.
- **Port belegt:** Setze `SMOKE_PORT=<frei>` und starte den Smoke-Test erneut.
- **Docker-Sektion:** Setze `SMOKE_UNIFIED_IMAGE` auf einen vorhandenen Tag, wenn du die optionale Container-Prüfung ausführen möchtest.

## Nachweise im PR

- Output von `make doctor` (Kurzfassung: `All doctor checks passed.`)
- Konsolenausschnitte jedes `make all`-Schrittes (mindestens die letzten 5–10 Zeilen pro Kommando).
- Aktualisierte Wiring-/Removal-Reports im PR-Body.
- Hinweise auf besondere Overrides (z. B. alternative Ports, deaktivierte Worker) in den PR-Notizen.
