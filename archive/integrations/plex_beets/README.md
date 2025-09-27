# Plex & Beets Integrationen (archiviert)

Die ursprünglichen Plex- und Beets-Integrationen wurden für das MVP deaktiviert
und der Code hier abgelegt. Die Dateien bleiben unverändert, damit eine spätere
Reaktivierung per Revert/Move möglich ist.

## Wiederherstellungsschritte
1. Dateien aus diesem Ordner zurück in `app/` bewegen (Clients, Router, Worker).
2. Abhängigkeiten wie `plexapi` erneut zu den Requirements hinzufügen.
3. Feature-Flags `ENABLE_PLEX`/`ENABLE_BEETS` wieder aktivieren und Startup-Routine
   anpassen.
4. Tests und Health-Checks für Plex/Beets reaktivieren.
