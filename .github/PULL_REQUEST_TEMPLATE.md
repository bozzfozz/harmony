## Kurzfassung
**Was/Warum:**  
**TASK_ID:** <z. B. CODX-XXX-123> (muss existieren; basiert auf `docs/task-template.md`)

## Änderungen (Dateien)
- Neu/Geändert/Gelöscht:

## Tests & Nachweise
- Befehle/Logs/Screens:
- Coverage (geänderte Module): ≥ 85 % | Begründete Ausnahme:

## Verträge
- Public-API: unverändert / geändert (OpenAPI aktualisiert)
- DB-Bootstrap: nein / ja (Schema-Erweiterungen via `Base.metadata.create_all()` dokumentiert)

## Deployment & Ops
- Datenbank neu initialisiert (`DB_RESET=1` + Startlogs angehängt): ja/nein
- ENV-Defaults geprüft/kommuniziert (siehe README „Orchestrator & Queue-Steuerung“, `docs/workers.md`):

## Doku & ToDo
- README/CHANGELOG/ADR aktualisiert: ja/nein
- ToDo.md aktualisiert (Nachweis-Link):

## Checkliste
- [ ] AGENTS.md gelesen & Scope-Guard geprüft
- [ ] Keine Secrets/`BACKUP`/Lizenzdateien verändert
- [ ] `pytest -q`, `mypy app`, `ruff`, `black --check` grün oder Ausnahme dokumentiert
