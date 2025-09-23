# Changelog

Alle nennenswerten Änderungen dieses Projekts werden in dieser Datei dokumentiert.

## v1.x.x – Service-Konfiguration über die UI
- Einstellungen für Spotify, Plex und Soulseek sind jetzt direkt in der UI pflegbar.

## v1.x.x – Harmony AppHeader
- Neuer Harmony AppHeader im Frontend hinzugefügt.

## v1.6.0 – Harmony Web UI
- Vollständige Web-Oberfläche mit Spotify, Plex, Soulseek, Matching und Settings implementiert.
- Globale Suche, Filter, Notifications und Theme-Steuerung über den AppHeader.
- Realtime-Updates via SSE für Soulseek-Downloads und Plex-Scans integriert.
- Services, Hooks und Tests für API-Aufrufe, Matching-Flows und Formularspeicherung hinzugefügt.

## v1.5.0 – Frontend-Grundstruktur
- Frontend-Grundstruktur mit Navbar, Sidebar, Routing und ersten Pages erstellt.
- React + Vite Setup mit Tailwind, shadcn/ui und Radix UI eingerichtet.
- Navigationslayout bestehend aus fixer Navbar, Sidebar und mobilem Drawer hinzugefügt.
- Erste UI-Module (Cards, Tabellen, Formulare, Toasts) vorbereitet.

## v0.3.0 – Theme-System
- Theme-System (Light/Dark) integriert.
- CSS-Variablen für Farben und Radii definiert und in Tailwind verfügbar gemacht.
- Dark-Mode Toggle inklusive Persistenz eingebaut.

## v1.4.0 – Spotify API Vollintegration
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
