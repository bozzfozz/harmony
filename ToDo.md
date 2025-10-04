ID: TD-20251004-002
Titel: Service Health akzeptiert gemischte Groß-/Kleinschreibung
Status: done
Priorität: P2
Scope: backend
Owner: codex
Created_at: 2025-10-04T13:46:28Z
Updated_at: 2025-10-04T13:46:28Z
Tags: service-health, configuration
Beschreibung: Mixed-Case-Service-Namen führten bei den Health-Hilfsfunktionen zu KeyError-Ausnahmen. Die neue Normalisierung sorgt dafür, dass sowohl evaluate_service_health als auch collect_missing_credentials unabhängig von der Schreibweise funktionieren. Tests decken die Regression ab und verhindern erneute Einführungen des Fehlers.
Akzeptanzkriterien:
- evaluate_service_health akzeptiert Service-Namen mit beliebiger Groß-/Kleinschreibung und liefert den kanonischen Namen zurück.
- collect_missing_credentials verarbeitet gemischt geschriebene Service-Namen ohne Ausnahme und meldet fehlende Credentials mit kanonischem Schlüssel.
Risiko/Impact: Niedrig; reine Normalisierung ohne Auswirkungen auf bestehende Aufrufer.
Dependencies: Keine
Verweise: PR TBD
Subtasks:
- Normalisierung der Service-Namen implementieren.
- Regressionstests für gemischt geschriebene Service-Namen ergänzen.
