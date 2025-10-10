# RUNBOOK — Harmony Download Manager (HDM) (Spotify PRO OAuth Upgrade)

Dieser Runbook richtet sich an Operator:innen, die den HDM-End-to-End-Fluss
(vormals „FLOW-002“) bereitstellen, überwachen und im Fehlerfall
wiederherstellen müssen. Ein architektonischer Überblick steht im Abschnitt
[„Harmony Download Manager (HDM) – Spotify PRO OAuth Upgrade“](README.md#harmony-download-manager-hdm--spotify-pro-oauth-upgrade).
Der Audit-Status ist in [AUDIT-HDM.md](AUDIT-HDM.md) dokumentiert.

## Betriebsziele

- Spotify PRO muss `authorized: true` in `GET /spotify/status` liefern.
- Backfill- und Watchlist-Worker dürfen keine OAuth-bedingten Fehler im DLQ
  hinterlassen (`reports/dlq/*.jsonl` bleibt leer).
- Der OAuth-State-Store bleibt unter 50 offenen Transaktionen (`/metrics` →
  `oauth_transactions_active`).
- Recovery-Schritte müssen remote durchführbar sein (siehe
  [Docker OAuth Fix](README.md#docker-oauth-fix-remote-access)).

## Vorbereitungen

1. **Zugänge:** Spotify Developer Console (Client-ID/Secret), API-Key für Harmony,
   Zugang zum Container-Host.
2. **Umgebung:** Stellen Sie sicher, dass die Variablen aus dem README-Abschnitt
   [„Relevante Umgebungsvariablen“](README.md#relevante-umgebungsvariablen)
   gesetzt sind. Geheimnisse niemals ins Repo schreiben.
3. **Verzeichnisse:**
   - `/data` (Downloads & Musik) — Schreibrechte `uid=1000` bzw. `chmod 775`.
   - `reports/` (DLQ, Coverage, JUnit) — `chmod 775`, falls hostpersistent genutzt.
   - Optional eingehängte Secrets (`/run/secrets/*` oder `/var/lib/harmony/oauth`) —
     `chmod 700` (Dirs) / `chmod 600` (Files).
4. **Netzwerk:** Ports `8080/tcp` (API) und `8888/tcp` (OAuth Callback) müssen
   erreichbar sein. Bei entfernten Hosts SSH-Port-Forwarding vorbereiten.

## Standardbetrieb

1. **Container starten:** Verwenden Sie die im README dokumentierten
   Docker-Compose-Profile oder den Beispiel-`docker run`-Befehl. Prüfen Sie die
   Logs (`docker logs -f harmony`) auf die Meldung
   `oauth.service: ready (client_id=***set***).`
2. **OAuth initialisieren:** Navigieren Sie zur Einstellungen-Seite im Frontend
   und starten Sie „Spotify PRO verbinden“. Stellen Sie sicher, dass das Popup
   nicht geblockt wird. Alternativ können Sie
   `POST /api/v1/spotify/pro/oauth/start` per API aufrufen.
3. **Callback bestätigen:** Nach erfolgreichem Consent sollte das Frontend
   automatisch schließen und `GET /spotify/status` `authorized: true`
   melden. In Logs erscheint `oauth.service: authorization completed`.
4. **Backfill beobachten:** Prüfen Sie `GET /api/v1/backfill/status` sowie die
   Worker-Logs (`download`, `watchlist`). Der Flow ist abgeschlossen, wenn neue
   Tasks mit Spotify-Metadaten ohne Fehler persistiert sind.

## Monitoring & Observability

| Signal | Quelle | Erwartungswert |
| --- | --- | --- |
| `oauth_transactions_active` | Prometheus (`/metrics`) | < 5 im Normalbetrieb |
| `oauth.exchange.success` | strukturierte Logs (`oauth_service`) | Anstieg bei erfolgreichem Token-Tausch |
| `oauth.exchange.error` | Logs | 0; jede Erhöhung prüfen |
| `spotify.api.errors` | Logs (`integrations.spotify`) | 0 für 2xx-Calls, Retry-Warnungen toleriert |
| `backfill.jobs.queued` | Orchestrator-Metrik (Logs) | kurzfristige Peaks ok, < 200 langfristig |

Weitere Details zu Logging-Konventionen stehen in
[docs/observability.md](docs/observability.md).

## Häufige Störungen & Behebung

### OAuth-Token wiederherstellen

**Symptome:** `GET /spotify/status` meldet `authorized: false`, Worker loggen
`OAUTH_TOKEN_EXCHANGE_FAILED` oder `OAUTH_CODE_EXPIRED`.

**Schritte:**

1. Führen Sie erneut `POST /api/v1/spotify/pro/oauth/start` aus.
2. Sollte der Callback nicht ankommen, verwenden Sie den
   [Docker OAuth Fix](README.md#docker-oauth-fix-remote-access) und senden Sie die
   komplette Redirect-URL an `POST /api/v1/oauth/manual`.
3. Prüfen Sie die Metrik `oauth.exchange.success`. Bei Erfolg setzt das Backend
   `authorized: true`.
4. Falls weiterhin Fehler auftreten, starten Sie den Container neu oder warten
   mindestens die konfigurierte TTL (Default: 10 Minuten), damit abgelaufene
   States automatisch aus dem In-Memory-Store entfernt werden. Dieser Schritt ist
   idempotent; fehlgeschlagene Exchanges hinterlassen keine persistierten Secrets.

### Secrets rotieren

**Symptome:** Sicherheitswechsel in der Spotify Developer Console.

**Schritte:**

1. Setzen Sie temporär `HARMONY_DISABLE_WORKERS=true` (z. B. via
   `docker compose run --rm --service-ports harmony` mit Override oder durch ein
   Environment-Update) und starten Sie den Container neu, damit keine neuen Jobs
   gezogen werden.
2. Aktualisieren Sie `SPOTIFY_CLIENT_ID` und `SPOTIFY_CLIENT_SECRET` als ENV oder
   im Secret-Store (`PATCH /api/v1/settings/secrets`).
3. Entfernen Sie den Override (`HARMONY_DISABLE_WORKERS=false`) und führen Sie
   einen erneuten Deploy/Restart durch.
4. Durchlaufen Sie anschließend „OAuth-Token wiederherstellen“.

### Callback-Port remote nicht erreichbar

**Symptome:** Spotify-Consent endet mit `ERR_CONNECTION_TIMED_OUT` oder der
Browser kann `127.0.0.1:8888` nicht erreichen.

**Schritte:**

1. Prüfen Sie Firewall-Regeln und Docker-Port-Mappings (`docker ps --format`).
2. Öffnen Sie einen SSH-Tunnel: `ssh -N -L 8888:127.0.0.1:8888 user@host`.
3. Wiederholen Sie den OAuth-Flow oder senden Sie die Redirect-URL an
   `POST /api/v1/oauth/manual`.
4. Dokumentieren Sie den Remote-Fix im Incident-Log (Ticket, Slack-Thread).

### DLQ und Backfill

**Symptome:** `reports/dlq/backfill-*.jsonl` enthält Spotify-spezifische Fehler.

**Schritte:**

1. Greifen Sie die fehlerhaften Items via `scripts/dlq/replay_backfill.py` ab.
2. Prüfen Sie, ob die OAuth-Token gültig sind (`GET /spotify/status`).
3. Wiederholen Sie den Backfill mit `POST /api/v1/backfill/retry` oder führen Sie
   `python scripts/dlq/replay_backfill.py --once` im Container aus.
4. Schließen Sie den Incident, sobald `reports/dlq/` leer ist und die
   Metadaten aktualisiert wurden.

## Eskalation

- **SRE-Rotation:** TODO (PagerDuty-Handle aktualisieren).
- **Produkt-Owner Spotify:** TODO (Ansprechpartner: Spotify Verantwortliche).
- **Vendor:** Spotify Support (Dashboard → _Contact Us_ → „Production Outage“).

Alle Eskalationen sollten in der zentralen Incident-Dokumentation referenziert
werden. Aktualisieren Sie `AUDIT-HDM.md`, sobald neue Kontrollen eingeführt
werden.
