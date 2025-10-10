# AUDIT — Harmony Download Manager (HDM) Traceability

- **Status:** GO (alle Kontrollen erfüllt)
- **Letzte Prüfung:** 2025-10-10
- **Verantwortlich:** Platform Engineering (Spotify Integrationen)

## Traceability Matrix

| Anforderung / Kontrolle | Implementierung | Evidenz | Status |
| --- | --- | --- | --- |
| OAuth-Secrets müssen sicher verwaltet werden | ENV-Variablen + Secret-Store gemäß [README](README.md#relevante-umgebungsvariablen) und [RUNBOOK Abschnitt „Secrets rotieren“](RUNBOOK_HDM.md#secrets-rotieren) | Audit-Log `settings.secrets` + Konfigurations-Review | GO |
| Remote-Bedienbarkeit des OAuth-Callbacks | [README: Docker OAuth Fix](README.md#docker-oauth-fix-remote-access) + [Runbook: OAuth-Token wiederherstellen](RUNBOOK_HDM.md#oauth-token-wiederherstellen) | Erfolgreicher Remote-Fix-Test (Ticket referenziert) | GO |
| Monitoring der OAuth-Flows | [Runbook Monitoring-Tabelle](RUNBOOK_HDM.md#monitoring--observability) | Prometheus-Dashboard `hdm` | GO |
| Backfill-Fehlerbehandlung dokumentiert | [RUNBOOK Abschnitt „DLQ und Backfill“](RUNBOOK_HDM.md#dlq-und-backfill) | DLQ-Review-Checklist (operations repo) | GO |
| Operator:innen-Leitfaden verfügbar | [README HDM](README.md#harmony-download-manager-hdm--spotify-pro-oauth-upgrade) + [Runbook](RUNBOOK_HDM.md) | Docset-Versionierung in Git | GO |

## Nachweise & Referenzen

- Incident-Records: Siehe internes Ticket-System (`HDM-*`, vormals `FLOW-002-*`).
- Änderungen werden per Pull Request mit Verweis auf diese Audit-Datei dokumentiert.
- Aktualisierungen der Kontrollen bedürfen einer erneuten Review durch Platform Engineering.
