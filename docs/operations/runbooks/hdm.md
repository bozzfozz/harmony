# RUNBOOK — Harmony Download Manager (HDM) (Spotify PRO OAuth Upgrade)

Dieser Runbook richtet sich an Operator:innen, die den HDM-End-to-End-Fluss
bereitstellen, überwachen und im Fehlerfall
wiederherstellen müssen. Ein architektonischer Überblick steht in
[„Harmony Download Manager (HDM)“](../../architecture/hdm.md).
Der Audit-Status ist in [HDM Audit](../../compliance/hdm_audit.md) dokumentiert.

## Betriebsziele

- Spotify PRO muss `authorized: true` in `GET /spotify/status` liefern.
- Backfill- und Watchlist-Worker dürfen keine OAuth-bedingten Fehler im DLQ
  hinterlassen (`reports/dlq/*.jsonl` bleibt leer).
- Der OAuth-State-Store bleibt unter 50 offenen Transaktionen (`/metrics` →
  `oauth_transactions_active`).
- Recovery-Schritte müssen remote durchführbar sein (siehe
  [Spotify OAuth Guide](../../auth/spotify.md#callback-on-remote-hosts)).

## Vorbereitungen

1. **Zugänge:** Spotify Developer Console (Client-ID/Secret), API-Key für Harmony,
   Zugang zum Container-Host.
2. **Umgebung:** Stellen Sie sicher, dass die Variablen aus der
   [Konfigurationsreferenz](../../configuration.md)
   gesetzt sind. Geheimnisse niemals ins Repo schreiben.
3. **Verzeichnisse:**
   - `/data` (Downloads & Musik) — Schreibrechte `uid=1000` bzw. `chmod 775`.
   - `reports/` (DLQ, Coverage, JUnit) — `chmod 775`, falls hostpersistent genutzt.
   - Optional eingehängte Secrets (`/run/secrets/*` oder `/var/lib/harmony/oauth`) —
     `chmod 700` (Dirs) / `chmod 600` (Files).
4. **Netzwerk:** Ports `8080/tcp` (API) und `8888/tcp` (OAuth Callback) müssen
   erreichbar sein. Bei entfernten Hosts SSH-Port-Forwarding vorbereiten.

## Go-Live-Checkliste

1. **Startup-Guards ausführen:** `python -m app.ops.selfcheck --assert-startup`
   muss mit Exit-Code `0` enden. Die wichtigsten Exit-Codes:
   - `78 (EX_CONFIG)`: Pflicht-ENV/Secrets fehlen (`SPOTIFY_CLIENT_*`,
     `HARMONY_API_KEY`, `OAUTH_STATE_DIR` bei Split-Mode).
   - `71 (EX_OSERR)`: Verzeichnisse (`DOWNLOADS_DIR`, `MUSIC_DIR`, ggf.
     `OAUTH_STATE_DIR`) existieren nicht oder sind nicht beschreibbar.
   - `69 (EX_UNAVAILABLE)`: abhängige Dienste nicht erreichbar (`SLSKD_BASE_URL`
     bzw. `SLSKD_HOST`/`SLSKD_PORT`,
     Datenbank bei `HEALTH_READY_REQUIRE_DB=true`).
   - `70 (EX_SOFTWARE)`: interne Fehlkonfiguration (z. B. ungültige Ports oder
     fehlerhafte Booleans).
2. **Health-API prüfen:**
   - `GET /live` → `200 {"status": "ok"}` (`/api/health/live` bleibt als Alias erhalten).
   - `GET /api/health/ready?verbose=1` → `200` und alle Checks auf `ok`.
3. **Volumes & Rechte:** Download- und Musik-Verzeichnis mit Test-Datei
  beschreibbar (`touch`, `fsync`, `rm`).
  - HDM erzwingt bei Cross-Device-Moves jetzt einen `fsync` auf der temporären
    Kopie und dem Zielverzeichnis, bevor es per Rename finalisiert. Achten Sie
    in den Logs auf `hdm.move.copy_fallback.succeeded`, wenn unterschiedliche
    Mounts involviert sind.
  - Die Laufzeit (`build_hdm_runtime` → `DefaultDownloadPipeline`) injiziert den
    `AtomicFileMover`, der die Dateiübergabe steuert und beim Schritt
    `file.moved` ausgeführt wird.
4. **OAuth-State:** Bei Split-Mode sicherstellen, dass `OAUTH_STATE_DIR`
   auf demselben Dateisystem wie `DOWNLOADS_DIR` liegt (siehe Self-Check).
5. **Secrets-Dokumentation:** Rotationstermine und Speicherort der Secrets
   (Spotify, API-Key, Datenbank) aktualisieren.

## Standardbetrieb

1. **Container starten:** Verwenden Sie die im README dokumentierten
   Docker-Compose-Profile oder den Beispiel-`docker run`-Befehl. Prüfen Sie die
   Logs (`docker logs -f harmony`) auf die Meldung
   `oauth.service: ready (client_id=***set***).`
2. **OAuth initialisieren:** Navigieren Sie zur Einstellungen-Seite im Frontend
   (siehe [Spotify UI Operations Guide](../../ui/spotify.md) für eine
   Kartenübersicht) und starten Sie „Spotify PRO verbinden“. Stellen Sie sicher,
   dass das Popup nicht geblockt wird. Alternativ können Sie
   `POST /api/v1/spotify/pro/oauth/start` per API aufrufen.
3. **Callback bestätigen:** Nach erfolgreichem Consent sollte das Frontend
   automatisch schließen und `GET /spotify/status` `authorized: true`
   melden. In Logs erscheint `oauth.service: authorization completed`.
4. **Backfill beobachten:** Prüfen Sie `GET /api/v1/backfill/status` sowie die
  Worker-Logs (`download`, `watchlist`). Der Flow ist abgeschlossen, wenn neue
  Tasks mit Spotify-Metadaten ohne Fehler persistiert sind.
5. **Manuellen Sync über das Dashboard anstoßen (optional):**
   1. Melden Sie sich mit einem Operator-Account in der UI an. Der Button
      erscheint nur, wenn die Feature-Flags `UI_FEATURE_SPOTIFY=true` und
      `UI_FEATURE_SOULSEEK=true` aktiv sind.
   2. Öffnen Sie die Dashboard-Ansicht. Im Abschnitt „Dashboard actions“
      befinden sich der Button **Trigger sync** sowie der Bereich „Manual sync
      status“.
   3. Klicken Sie auf **Trigger sync** und bestätigen Sie den Dialog „Trigger a
      manual sync run now?“. Während der Request läuft, deaktiviert die UI den
      Button (`aria-busy`).
   4. Beobachten Sie das Alert-Fragment über den Karten: erfolgreiche Läufe
      zeigen eine grüne Toast-Meldung, Fehler erscheinen rot.

   - Das Panel „Manual sync status“ aktualisiert sich automatisch per
     Out-of-band-Swap (HTMX) und zeigt Zeitstempel sowie Resultate der letzten
     Ausführung.
   - Der Status-Badge signalisiert `Success`, `Partial` oder `Failed`. `Partial`
     bedeutet, dass mindestens ein Subsystem Warnungen oder Fehler meldete.
   - Unter „Source status“ sehen Sie pro Quelle (z. B. Playlists, Library Scan,
     Auto Sync) den Rückgabestatus aus der API (`results`).
   - „Key metrics“ listet Zähler wie `tracks_synced`, `tracks_skipped` und
     `errors`.
   - „Warnings“ zeigt Normalisierungen aus `errors` (etwa fehlende Secrets);
     beheben Sie die Ursache und triggern Sie den Sync erneut.
   - Jede Ausführung erzeugt einen Logeintrag `ui.action.dashboard_sync` im
     Logger `app.ui.router` inklusive `status`, `results` und `errors`.
   - Falls der Button nicht sichtbar ist oder HTMX-Requests blockiert werden,
     führen Sie `POST /api/v1/sync` direkt mit API-Key aus und prüfen Sie
     anschließend das Dashboard erneut.

## Monitoring & Observability

| Signal | Quelle | Erwartungswert |
| --- | --- | --- |
| `oauth_transactions_active` | Prometheus (`/metrics`) | < 5 im Normalbetrieb |
| `oauth.exchange.success` | strukturierte Logs (`oauth_service`) | Anstieg bei erfolgreichem Token-Tausch |
| `oauth.exchange.error` | Logs | 0; jede Erhöhung prüfen |
| `spotify.api.errors` | Logs (`integrations.spotify`) | 0 für 2xx-Calls, Retry-Warnungen toleriert |
| `backfill.jobs.queued` | Orchestrator-Metrik (Logs) | kurzfristige Peaks ok, < 200 langfristig |
| `ui.action.dashboard_sync` | UI-Logs (`app.ui.router`) | Jeder manuelle Lauf sollte `status=success` loggen; Einträge mit `status=error` untersuchen |

Weitere Details zu Logging-Konventionen stehen in
[../../observability.md](../../observability.md).

## Häufige Störungen & Behebung

### OAuth-Token wiederherstellen

**Symptome:** `GET /spotify/status` meldet `authorized: false`, Worker loggen
`OAUTH_TOKEN_EXCHANGE_FAILED` oder `OAUTH_CODE_EXPIRED`.

**Schritte:**

1. Führen Sie erneut `POST /api/v1/spotify/pro/oauth/start` aus.
2. Sollte der Callback nicht ankommen, verwenden Sie den
   [Spotify OAuth Guide](../../auth/spotify.md#callback-on-remote-hosts) und senden Sie die
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

## QA & Tests

- Die historischen `tests/orchestrator/test_flow*.py`-Suiten wurden entfernt. Verwenden Sie die HDM-Regressionstests unter
  `tests/orchestrator/` (inklusive `tests/orchestrator/hdm/`) für End-to-End-Abnahmen.
- Das Guard-Skript `scripts/audit_wiring.py` blockiert Commits mit neuen `test_flow*`-Artefakten oder Referenzen. Analysieren Sie bei
  einem roten Gate die Job-Ausgabe und bereinigen Sie die gemeldeten Dateien.

### Frontend-Assets

Das frühere statische Frontend wurde entfernt. Der Runbook-Fokus liegt auf API und Hintergrunddiensten, bis das neue SSR-Interface verfügbar ist.

## Eskalation

- **SRE-Rotation:** `PD/Harmony-Platform` (PagerDuty).
- **Produkt-Owner Spotify:** Platform Engineering – Spotify Integrationen (Slack `#harmony-platform`).
- **Vendor:** Spotify Support (Dashboard → _Contact Us_ → „Production Outage“).

Alle Eskalationen sollten in der zentralen Incident-Dokumentation referenziert
werden. Aktualisieren Sie [HDM Audit](../../compliance/hdm_audit.md), sobald neue Kontrollen eingeführt
werden.
