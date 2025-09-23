# Changelog

Alle nennenswerten Änderungen dieses Projekts werden in dieser Datei dokumentiert.

## v2.0.0 – Harmony UI basierend auf Porttracker-Design
- Neue React/Vite/Tailwind Weboberfläche mit Dashboard, Service-Tabs, Tabellen und Settings-Formularen.
- Dark-/Light-Mode via Radix Switch, Toast-Benachrichtigungen und automatische Datenaktualisierung im 30 s-Takt.
- Anbindung der UI an bestehende APIs (`/spotify`, `/plex`, `/soulseek`, `/matching`, `/settings`, `/beets`).
- Jest + Testing Library für UI-Tests (Tabs, Settings-Formulare, Theme-Switch, Fehler-Handling).

## v1.4.0 – Spotify API Vollintegration
- Konfiguration für Spotify, Plex und slskd kann jetzt in der Datenbank persistiert und über die Settings-API gepflegt werden.
- Vollständige Spotify-Integration inkl. Playlist-Sync, Audio-Features, Recommendations und Benutzerbibliothek.
- Erweiterter Spotify-Router mit neuen Endpunkten für Playlists (Add/Remove/Reorder), Profil, Top-Tracks/-Artists.
- PlaylistSyncWorker synchronisiert persistierte Playlists regelmäßig in die Datenbank.

## v1.3.0 – Persistente Playlists
- Neuer Playlist-Sync-Prozess speichert Playlists persistent und liefert Änderungszeitpunkte.
- `/spotify/playlists` gibt Track-Anzahl und Timestamps aus der Datenbank zurück.

## v1.2.0 – Soulseek Downloadstatus
- Soulseek-Downloads werden mit Fortschritt und Zeitstempeln in SQLite abgelegt.
- API liefert Statusabfragen inklusive Fortschritt; Downloads können abgebrochen werden.
- Hintergrund-SyncWorker pollt slskd und aktualisiert persistierte Einträge.

## v1.1.0 – Beets-Integration
- Beets CLI via `BeetsClient` angebunden (Import, Update, Remove, Move, Write, Query, Stats).
- Dockerfiles und Compose-Setup für konsistenten Start angepasst.

## v1.0.0 – Initiale Version
- FastAPI-Anwendung mit Spotify-, Plex- und Soulseek-Routern.
- SQLite + SQLAlchemy für Persistenz, inklusive Testabdeckung mittels Pytest.
