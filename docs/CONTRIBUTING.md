# Harmony Contribution Guide

Dieses Dokument richtet sich an alle Contributor:innen (Team & externe Partner)
und ergänzt die Vorgaben aus `AGENTS.md` sowie dem PR-Template.

## Vor der Implementierung
- Synchronisiere die Abhängigkeiten mit `uv sync`, damit lokale Läufe dem
  CI-Stack entsprechen.
- Erstelle ein Ticket auf Basis von [`docs/task-template.md`](task-template.md)
  und sammle dort Scope, Risiken und Tests.
- Prüfe bestehende ADRs unter [`docs/architecture/adr/`](architecture/adr/).
  Neue Entscheidungen dokumentierst du mit [`0000-template.md`](architecture/adr/0000-template.md).
- Kläre Architekturimplikationen frühzeitig mit dem Architecture-Channel.

## Pull-Request-Anforderungen
- Verwende das Template `.github/PULL_REQUEST_TEMPLATE.md` vollständig.
- Bestätige explizit das Pflicht-Kontrollkästchen **„Architektur-Dokumente
  geprüft/aktualisiert“**. Damit bestätigst du, dass Änderungen an
  Komponenten/Integrationen in den relevanten Dokumenten nachgezogen wurden (siehe
  [`docs/architecture/README.md`](architecture/README.md)).
- Führe `uv run make doctor`, `uv run make all` und `uv run make docs-verify`
  lokal aus; hänge die Logs im PR an. Ergänze eigenständige Testläufe mit
  `uv run pytest`, wenn du gezielt Testmodule validierst.
- Dokumentiere im PR-Text, welche ADRs oder Architekturdateien ergänzt bzw.
  angepasst wurden. Verlinke neue ADRs direkt.

## Review & Approval
- Reviewer:innen blocken PRs ohne ADR-Referenz oder ohne Bestätigung des
  Architektur-Checkboxes.
- Nutze die Review-Kommentare, um fehlende ADRs oder Dokumentationsupdates
  anzufordern. Merge erfolgt erst, wenn alle Pflicht-Nachweise vorliegen.

## Nach dem Merge
- Aktualisiere bei Bedarf `docs/overview.md`, Roadmaps oder Projektstatus-Dateien.
- Kommuniziere neue Architekturentscheidungen im Team-Standup bzw. im
  Architecture-Channel, damit Folgearbeiten geplant werden können.
