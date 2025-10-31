# Docs Reference Guard

Der Guard [`scripts/docs_reference_guard.py`](../../scripts/docs_reference_guard.py) prüft, ob alle zitierten oder verlinkten Dateien innerhalb des Repositories existieren. Er wird über das Makefile-Target [`make docs-verify`](../../Makefile) aufgerufen und muss in der CI grün sein.

## Überwachte Dateien

Im Standardlauf kontrolliert der Guard aktuell folgende Gruppen:

1. Wichtige Einzel-Dateien
   - `README.md`
   - `CHANGELOG.md`
   - `docs/README.md`
   - `docs/overview.md`
   - `docs/architecture.md`
   - `docs/observability.md`
   - `docs/security.md`
   - `docs/testing.md`
   - `docs/project_status.md`
   - `docs/troubleshooting.md`
   - `docs/operations/runbooks/hdm.md`
2. Ganze Verzeichnisbäume
   - `docs/operations/` (inkl. aller Runbooks)
   - `docs/process/` (Prozessdokumentation, inkl. dieser Datei)
   - `reports/` (operative Reports wie `reports/api/*` und `reports/ui/*`)

## Broken Links beheben

Der Guard bricht mit Exit-Code `1` ab, sobald ein Link auf eine nicht vorhandene Datei verweist. Im Fehlerfall:

1. Datei und Zeilennummer aus dem Fehler-Log entnehmen.
2. Pfad korrigieren oder die referenzierte Datei anlegen.
3. `make docs-verify` erneut ausführen.

## Neue Dokumente überwachen

Neue Schlüssel-Dokumente werden über die Konstanten `DEFAULT_DOC_PATHS` (Einzeldateien) bzw. `DEFAULT_DOC_DIRECTORIES` (Verzeichnisse) in `scripts/docs_reference_guard.py` registriert. Beim Hinzufügen neuer Bereiche:

1. Die entsprechende Liste erweitern.
2. `make docs-verify` lokal ausführen.
3. Änderung im Review festhalten.

> **Hinweis:** Für rein lokale oder temporäre Dokumente ist keine Registrierung nötig. Nur zentral veröffentlichte oder operativ relevante Inhalte sollten in den Standardlauf aufgenommen werden.
