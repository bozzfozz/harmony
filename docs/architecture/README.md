# Architektur-Dokumentationsleitfaden

Dieser Index bündelt alle Architektur-Referenzen von Harmony. Nutze ihn als
Checkliste, sobald du Komponenten, Laufzeitgrenzen oder Integrationspfade
änderst.

## Pflicht-Updates bei Architekturänderungen
- [`docs/architecture.md`](../architecture.md) – High-Level-Überblick und
  Systemscope. Hier jede Änderung an Plattformgrenzen, Provider-Support oder
  Kern-Workflows dokumentieren.
- [`docs/architecture/overview.md`](overview.md) – Detaillierte
  Komponentenbeschreibung inklusive Sequenzen. Passe sie an, wenn neue Services,
  Router oder
  Worker eingeführt werden oder bestehende Verantwortlichkeiten rotieren.
- [`docs/architecture/diagrams.md`](diagrams.md) – Quelle für Diagramme und
  Visuals. Aktualisiere Screenshots/Draw.io-Dateien gemeinsam mit Änderungen an
  den beschriebenen Flows.
- [`docs/architecture/contracts.md`](contracts.md) – Schnittstellenverträge und
  Datenflüsse. Ergänze/ändere Einträge, wenn APIs, Events oder Datenmodelle
  angepasst werden.
- [`docs/architecture/hdm.md`](hdm.md) – Spezifika des Harmony Download
  Managers. Pflege Änderungen an Worker-Pipelines, Queues oder Retry-Strategien.

## Architecture Decision Records (ADR)
- [`docs/architecture/adr/`](adr/) enthält die nummerierten ADRs.
- Nutze [`0000-template.md`](adr/0000-template.md) für neue Entscheidungen.
- Jede Änderung an Architekturprinzipien oder langfristigen Trade-offs erfordert
  einen neuen oder aktualisierten ADR.

## Ablauf für Pull Requests
1. Prüfe, ob deine Änderung Architektur- oder Integrationspfade berührt.
2. Aktualisiere die oben genannten Dateien und füge neue ADRs hinzu (falls
   notwendig).
3. Bestätige im PR-Template das Kontrollkästchen **„Architektur-Dokumente
   geprüft/aktualisiert“**.
4. Verlinke relevante ADRs und führe im PR-Text kurz aus, welche Dokumente
   angepasst wurden.
5. Führe `make docs-verify` aus, damit der Docs Reference Guard alle Links und
   Verweise erneut prüft.

## Verantwortlichkeiten
- Reviewer:innen blocken PRs, in denen Architektur-Änderungen ohne passende
  Dokumentationsupdates eingehen.
- Bei Unsicherheiten eskaliere frühzeitig im Architektur-Channel und halte die
  Entscheidung anschließend per ADR fest.
