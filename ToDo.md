ID: TD-20251012-002
Titel: SQLite-Queue erhält robuste Idempotenz-Garantie
Status: todo
Priorität: P1
Scope: backend
Owner: codex
Created_at: 2025-10-12T15:00:00Z
Updated_at: 2025-10-12T15:00:00Z
Tags: queue, sqlite, reliability
Beschreibung: Die aktuelle Fallback-Logik für SQLite-ON-CONFLICT führt zu zusätzlicher Komplexität und birgt das Risiko, dass Idempotenz über mehrere Prozesse hinweg nicht garantiert bleibt. Wir benötigen eine belastbare Lösung (Migration oder Schema-Anpassung), damit die Queue auch in Test- und Embedded-Umgebungen denselben Schutz wie in Postgres erhält.
Akzeptanzkriterien:
- QueueJob-Tabelle besitzt einen funktionierenden UNIQUE-Index für (type, idempotency_key) in SQLite-Umgebungen.
- _upsert_queue_job() kann den Fallback entfernen und verlässt sich wieder auf einheitliche UPSERT-Semantik.
- Tests decken konkurrierende Enqueue-Szenarien ohne Fallback-Pfade ab.
Risiko/Impact: Mittel; Änderungen an Migrationslogik können bestehende Tests beeinflussen.
Dependencies: Datenbank-Migrationspfad für SQLite.
Verweise: TASK TBD
Subtasks:
- Analyse der bestehenden Alembic-Migrationen und SQLite-Einschränkungen.
- Implementierung des neuen Index/Migrationspfads samt Tests.
- Entfernen der temporären Fallback-Logik und Regressionstests.

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

ID: TD-20251012-003
Titel: Spotify PRO Buttons triggern OAuth-Fluss direkt
Status: todo
Priorität: P2
Scope: frontend
Owner: codex
Created_at: 2025-10-12T16:30:00Z
Updated_at: 2025-10-12T16:30:00Z
Tags: spotify, ux, integrations
Beschreibung: Die Spotify-Übersicht blendet jetzt PRO-spezifische Aktionen ein, doch die Buttons leiten lediglich auf allgemeine Seiten weiter. Für einen konsistenten Flow sollen Nutzer:innen den OAuth-Anmeldeprozess direkt aus der Oberfläche starten und den Status der Authentifizierung live sehen können. Zudem fehlt ein klarer Abschluss-Dialog nach erfolgreichem Login, der auf verfügbare PRO-Funktionen verweist. Ziel ist eine nahtlose UX ohne manuelle Kontextwechsel in Backend-Tools. Die Umsetzung sollte Telemetrie-Hooks berücksichtigen, um Fehlversuche zu analysieren und Retry-Hinweise zu geben.
Akzeptanzkriterien:
- PRO-Aktionsbuttons öffnen einen OAuth-Dialog inklusive Callback-Verarbeitung innerhalb des Frontends.
- Nach erfolgreicher Authentifizierung aktualisiert sich der Status-Bereich automatisch ohne Reload.
- Nutzer:innen erhalten einen Abschluss-Hinweis mit Links zu Watchlist, Künstlerbibliothek und Backfill-Aufträgen.
Risiko/Impact: Mittel; Fehler im OAuth-Flow könnten den Zugriff auf PRO-Funktionen blockieren.
Dependencies: Harmonys OAuth-Endpunkt und Redirect-Konfiguration.
Verweise: TASK TBD
Subtasks:
- OAuth-Start-Endpoint aus dem Frontend ansteuern und Redirect-Handling implementieren.
- Status-Polling nach Auth-Callback integrieren und UI-Feedback ergänzen.
- Tracking für erfolgreiche und gescheiterte OAuth-Versuche hinzufügen.

ID: TD-20251012-005
Titel: Matching-Scoring mit Album-Trackzahlen validieren
Status: todo
Priorität: P2
Scope: backend
Owner: codex
Created_at: 2025-10-12T17:00:00Z
Updated_at: 2025-10-12T17:00:00Z
Tags: matching, scoring, integrations
Beschreibung: Die neuen Bonusroutinen für Album-Trackzahlen sind bislang nur durch Unit-Tests abgesichert. Um Regressionen zu vermeiden, sollen repräsentative Provider-Datensätze gesammelt und End-to-End-Matchingläufe mit unterschiedlichen Albumgrößen dokumentiert werden. Zusätzlich braucht es Monitoring-Kennzahlen, die Trackcount-Abweichungen und deren Einfluss auf Scores sichtbar machen. Erkenntnisse aus den Tests sollen in die Matching-Konfiguration einfließen und dokumentiert werden.
Akzeptanzkriterien:
- Beispielhafte Spotify- und Soulseek-Datensätze werden mit realistischen Trackcount-Verteilungen gepflegt und versioniert.
- Automatisierte Integrationstests prüfen Bonus und Penalty bei Trackcount-Abgleich in der Matching-Pipeline.
- Dashboards oder Logs erfassen Trackcount-Deltas inklusive Score-Verlauf zur Laufzeit.
Risiko/Impact: Mittel; falsche Kalibrierung kann Score-Vertrauen mindern oder Downloads blockieren.
Dependencies: Matching-Konfigurations- und Telemetrie-Pipeline.
Verweise: TASK TBD
Subtasks:
- Datensätze recherchieren und als Fixtures aufbereiten.
- Integrationstests für Matching-Flows ergänzen.
- Monitoring-Hooks samt Dokumentation aktualisieren.

ID: TD-20251012-004
Titel: Sidebar-Kollapszustand persistieren
Status: todo
Priorität: P3
Scope: frontend
Owner: codex
Created_at: 2025-10-12T16:30:00Z
Updated_at: 2025-10-12T16:30:00Z
Tags: ui, accessibility
Beschreibung: Die neue Kollaps-Funktion der Sidebar merkt sich den Zustand derzeit nicht über Sitzungen hinweg. Nutzende müssen nach jedem Laden erneut einklappen. Eine Persistenz (z. B. LocalStorage) erhöht die Usability und stellt sicher, dass Tastatur- und Screenreader-Nutzende konsistent dieselbe Navigation vorfinden.
Akzeptanzkriterien:
- Sidebar merkt sich den letzten Kollapszustand über Reloads (z. B. mittels LocalStorage) und respektiert System- oder Nutzerpräferenzen.
- Persistenter Zustand beeinträchtigt mobile Breakpoints nicht und wird bei deaktiviertem Storage sauber gehandhabt.
- Tests decken Persistenz und Fallback auf Standardbreite ab.
Risiko/Impact: Niedrig; betrifft ausschließlich Client-State und UI-Interaktion.
Dependencies: Keine
Verweise: PR TBD
Subtasks:
- Persistenz-Hook oder Utility implementieren.
- Layout-Komponente aktualisieren und auf Konsistenz testen.
- Jest-Tests für gespeicherten Zustand ergänzen.
