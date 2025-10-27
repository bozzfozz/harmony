# SQLite-Runbook

Dieses Runbook dokumentiert, wie Harmony seine SQLite-Datenbank verwaltet und wie SRE-Teams Sicherungen, Restores und Health-Checks durchführen. PostgreSQL wird nicht mehr unterstützt; alle Deployments verlassen sich ausschließlich auf eine lokale Datei-Datenbank.

## Speicherort & Konfiguration

- **Default-DSN:** `sqlite+aiosqlite:///./harmony.db` (Entwicklung) bzw. `sqlite+aiosqlite:////config/harmony.db` (Staging/Prod). Die Pfade stammen aus `app/config.py` und können über `DATABASE_URL` überschrieben werden.
- **Persistenz:** Mountet bei Container-Deployments ein Volume unter `/config`, damit `harmony.db` und die generierte `harmony.yml` erhalten bleiben.
- **Reset:** Setze `DB_RESET=1`, um den Datenbank-File beim Start neu anzulegen. Ohne das Flag bleibt der vorhandene Inhalt erhalten.

## Startup & Health

- Der optionale Startup-Guard (`app.ops.selfcheck.run_startup_guards`) prüft, ob das Verzeichnis der Datenbank existiert und beschreibbar ist. Die Anwendung startet unabhängig vom Ergebnis und meldet Probleme ausschließlich über `/api/health/ready` bzw. den Guard-CLI-Exitcode.
- `/api/health/ready` zeigt den Status des Datenbank-Files (`exists`, `writable`, verwendeter Pfad) an. Das Endpoint-JSON enthält keine Postgres-Migrationsinformationen mehr.
- Für CI und Diagnose steht `python -m app.ops.selfcheck --assert-startup` zur Verfügung. Der Befehl nutzt dieselben Checks wie der Health-Endpunkt und kann Deployments optional hart stoppen.

## Backup & Restore

1. **Service anhalten** oder sicherstellen, dass keine Schreibvorgänge mehr stattfinden (SQLite sperrt Dateien während aktiver Transaktionen).
2. Die Datei `harmony.db` 1:1 kopieren (`cp /config/harmony.db /backups/harmony-$(date +%F).db`). Optional die `settings`-Tabelle exportieren (`sqlite3 harmony.db .dump settings`).
3. Für das Restore den Dienst stoppen, die Sicherung nach `/config/harmony.db` zurückkopieren und anschließend den Service erneut starten.
4. Nach dem Restore `/api/health/ready` prüfen und einen `SELECT count(*) FROM settings;` über `sqlite3` ausführen, um Leserechte zu verifizieren.

## Wartung & Diagnose

- **VACUUM/Analyse:** Bei großen Löschoperationen `sqlite3 harmony.db 'VACUUM;'` ausführen, um Speicherplatz freizugeben.
- **Integritätscheck:** `sqlite3 harmony.db 'PRAGMA integrity_check;'` sollte `ok` zurückgeben.
- **Dateirechte:** Der Service-User benötigt Schreibrechte auf das Verzeichnis, das `DATABASE_URL` referenziert. `/api/health/ready` bzw. `run_startup_guards` melden `Database file is not writable`, falls das nicht erfüllt ist.
- **Log-Metriken:** Fehlgeschlagene Zugriffe tauchen als `startup.failed`- oder `database.bootstrap`-Events im Log auf. Zusätzlich meldet `/api/health/ready` `status=fail` bei fehlenden Schreibrechten.

## Troubleshooting

| Symptom | Ursache | Lösung |
| --- | --- | --- |
| `Database file does not exist` beim Start | Verzeichnis nicht gemountet oder Volume leer | `/config`-Volume erstellen/mounten und Service neu starten. |
| Health-Endpoint zeigt `writable: false` | Dateirechte oder Readonly-Mount | Besitzrechte korrigieren (`chown <uid>:<gid> harmony.db`) bzw. Mount-Optionen anpassen. |
| `OperationalError: database is locked` | Parallele Schreibvorgänge blockieren sich | Worker-Batchgröße reduzieren (`WATCHLIST_*`), langfristig Jobs serialisieren. |
| CLI `sqlite3` nicht verfügbar im Container | Minimal-Image enthält das Binary nicht | Backup/Restore vom Host ausführen oder ein Debug-Image mit `sqlite3` verwenden. |

Weitere Ratschläge zu Laufzeit-Settings liefert die [Runtime Configuration](../ops/runtime-config.md).
