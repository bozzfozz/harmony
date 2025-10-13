## Kurzfassung
**Was/Warum:**
**TASK_ID:** <z. B. CODX-XXX-123> (muss existieren; basiert auf `docs/task-template.md`)

## Änderungen (Dateien)
- Neu/Geändert/Gelöscht:

## Tests & Nachweise
- Befehle/Logs/Screens (jeweils letzte Zeilen anfügen):
  - `make doctor`
  - `make all`
  - optionale Zusatzchecks (`mypy app`, `npm test`, `pip-audit` …)
- Wiring-Report (angepasste Aufrufer/Registrierungen/Exporte):
- Removal-Report (gelöschte Dateien + Begründung):

## Verträge
- Public-API: unverändert / geändert (OpenAPI aktualisiert)
- DB-Bootstrap: nein / ja (Schema-Erweiterungen via `Base.metadata.create_all()` dokumentiert)

## Deployment & Ops
- Datenbank neu initialisiert (`DB_RESET=1` + Startlogs angehängt): ja/nein
- ENV-Defaults geprüft/kommuniziert (siehe README „Orchestrator & Queue-Steuerung“, `docs/workers.md`):

## Doku & ToDo
- README/CHANGELOG/ADR aktualisiert: ja/nein
- ToDo.md aktualisiert (Nachweis-Link):

## Merge-Checkliste (ohne CI)
- [ ] AGENTS.md gelesen & Scope-Guard geprüft
- [ ] Keine Secrets/`BACKUP`/Lizenzdateien verändert
- [ ] `make doctor` **grün**
- [ ] `make all` **grün**
- [ ] `make foss-scan` ausgeführt (Report ohne Blocker)
- [ ] `pre-commit run --all-files`
- [ ] `pre-commit run --hook-stage push`
- [ ] Wiring-Report und Removal-Report im PR-Body gepflegt
- [ ] Logs der Pflichtläufe angehängt
