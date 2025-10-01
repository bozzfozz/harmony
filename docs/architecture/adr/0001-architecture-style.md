# ADR 0001 - Layered Services mit Orchestrator-Pattern

## Status
Accepted — 2025-10-02

## Kontext
Harmony integriert mehrere Domänenstränge (Spotify, Soulseek, Matching, Watchlist) über eine gemeinsame API. Nach dem Umbau von Orchestrator und Gateway fehlt eine versionierte Beschreibung des Zielbildes. Ohne klare Layer-Aufteilung drohen Service- und Router-Drift, duplizierte Fehlerbehandlungen sowie inkonsistente Idempotenz- und Retry-Strategien. Außerdem muss der ProviderGateway die heterogenen Integrationen kapseln, damit neue Provider ohne Refactoring der Services angebunden werden können.

## Entscheidung
Wir behalten ein klassisches Layered-Architecture-Modell (API → Application → Domain → Infrastructure) bei und kombinieren es mit einem eigenständigen Orchestrator-Pattern für Hintergrundjobs. Die Providerkommunikation erfolgt ausschließlich über den `ProviderGateway`, der DTOs validiert und Fehler auf die gemeinsame Taxonomie mappt. Structured Logging ist das primäre Observability-Mittel und folgt einem festen Schema. Neue Architekturentscheidungen werden via ADR festgehalten.

## Alternativen
- Monolithische Service-Layer ohne ProviderGateway: verworfen, da Integrationen dann domänenspezifische Codepfade in Services/Core platzieren würden und Idempotenz-/Retry-Logik nicht zentral versioniert wäre.
- Event-getriebene Microservices: verworfen, weil der aktuelle Scope (eine Deployable-Einheit) die bestehende Operations-Komplexität nicht rechtfertigt und zusätzliche Infrastruktur (Event-Bus, Outbox) benötigen würde.

## Konsequenzen
- Klare Verantwortlichkeiten pro Schicht, weniger Risiko für Architekturdrift.
- Provider-spezifische Anpassungen landen ausschließlich im Gateway oder dedizierten Adaptern, wodurch neue Provider reproduzierbar eingebunden werden können.
- Das Orchestrator-Pattern bleibt Quelle der Wahrheit für Jobs (Visibility, Heartbeats, DLQ) und benötigt regelmäßige Dokumentationspflege.
- Structured Logs ersetzen klassische Metriken; externe Observability-Systeme müssen JSON-Events konsumieren.

## Umsetzung & Follow-up
- Architekturübersicht, Verträge und Diagramme in `docs/architecture/` veröffentlichen und als Pflichtlektüre verankern.
- PR-Checkliste um Prüfung/Aktualisierung der Architektur-Dokumente erweitern.
- Neue Architekturentscheidungen über ADRs versionieren; Änderungen an Flows/Contracts sofort in `overview.md`, `contracts.md` und `diagrams.md` reflektieren.
