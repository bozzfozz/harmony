# AUDIT — Harmony Download Manager (HDM) Traceability

- **Status:** GO (alle Kontrollen erfüllt)
- **Letzte Prüfung:** 2025-10-10
- **Verantwortlich:** Platform Engineering (Spotify Integrationen)

## Traceability Matrix

| Anforderung / Kontrolle | Implementierung | Evidenz | Status |
| --- | --- | --- | --- |
| OAuth-Secrets müssen sicher verwaltet werden | ENV-Variablen + Secret-Store gemäß [Konfigurationsreferenz](../configuration.md) und [RUNBOOK Abschnitt „Secrets rotieren“](../operations/runbooks/hdm.md#secrets-rotieren) | Audit-Log `settings.secrets` + Konfigurations-Review | GO |
| Remote-Bedienbarkeit des OAuth-Callbacks | [Spotify OAuth Guide](../auth/spotify.md#callback-on-remote-hosts) + [Runbook: OAuth-Token wiederherstellen](../operations/runbooks/hdm.md#oauth-token-wiederherstellen) | Erfolgreicher Remote-Fix-Test (Ticket referenziert) | GO |
| Monitoring der OAuth-Flows | [Runbook Monitoring-Tabelle](../operations/runbooks/hdm.md#monitoring--observability) | Prometheus-Dashboard `hdm` | GO |
| Backfill-Fehlerbehandlung dokumentiert | [RUNBOOK Abschnitt „DLQ und Backfill“](../operations/runbooks/hdm.md#dlq-und-backfill) | DLQ-Review-Checklist (operations repo) | GO |
| Operator:innen-Leitfaden verfügbar | [HDM-Architektur](../architecture/hdm.md) + [Runbook](../operations/runbooks/hdm.md) | Docset-Versionierung in Git | GO |

## Nachweise & Referenzen

- Incident-Records: Siehe internes Ticket-System (`HDM-*`).
- Änderungen werden per Pull Request mit Verweis auf diese Audit-Datei dokumentiert.
- Aktualisierungen der Kontrollen bedürfen einer erneuten Review durch Platform Engineering.
