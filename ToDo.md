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

ID: TD-20251012-001
Titel: Soulseek- und Matching-Ansichten mit Live-Daten versorgen
Status: todo
Priorität: P2
Scope: frontend
Owner: codex
Created_at: 2025-10-12T09:00:00Z
Updated_at: 2025-10-12T09:00:00Z
Tags: navigation, integrations, soulseek, matching
Beschreibung: Die neuen Navigationspunkte für Soulseek und Matching zeigen aktuell nur Platzhaltertexte. Für ein vollständiges Nutzererlebnis müssen die Komponenten API-Aufrufe der Downloader- und Matching-Services integrieren. Zusätzlich soll die Navigation den aktuellen Integrationsstatus widerspiegeln und Rückmeldungen bei Fehlern geben. Dokumentation und Monitoring-Hooks müssen mit den neuen Ansichten abgeglichen werden.
Akzeptanzkriterien:
- SoulseekPage lädt Status- und Konfigurationsdaten aus dem Backend und visualisiert aktive Freigaben.
- MatchingPage zeigt laufende und ausstehende Zuordnungen inklusive Fehlerzuständen an.
- Navigation spiegelt den Integrationsstatus (z. B. Warnhinweise) wider und wird in der Doku beschrieben.
Risiko/Impact: Mittel; unvollständige Daten-Anbindung könnte zu verwirrenden Statusanzeigen führen.
Dependencies: Backend-Endpunkte für Soulseek- und Matching-Status.
Verweise: TASK TBD
Subtasks:
- API-Clients für Soulseek- und Matching-Status implementieren.
- UI-Komponenten zur Visualisierung der Statusdaten ergänzen.
- Monitoring- und Doku-Updates erstellen.
