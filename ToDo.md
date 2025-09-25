# ToDo

## ✅ Erledigt
- Basis-Backend mit FastAPI und Routern (Spotify, Plex, Soulseek, Matching, Settings)  
- Clients für Spotify, Plex, Soulseek, Beets  
- Worker für Sync, Matching, Scan, AutoSync  
- Spotify-Integration inkl. Playlists und Suche  
- Smart Matching mit Konfidenz-Scores  
- Concurrent Downloads über SyncWorker  
- Retry-Logik mit Backoff  
- AutoSync-Playlists  
- Auto-Database-Updates (grundlegend)  
- Plex-Scans über ScanWorker  

---

## ⬜️ Offen

### Core Features
- **Smart Search erweitern**: Filteroptionen für Genre, Jahr, Qualität im `/api/search` Endpunkt ergänzen.  
- **Complete Discographies**: Endpunkt + Worker-Logik für komplette Künstlerdiskografien mit automatischer Kategorisierung entwickeln.  
- **Rich Metadata**: Erweiterung der Datenbank und Worker, um Genre, Komponist, Produzent, ISRC, Copyright zu speichern.  
- **High-Quality Artwork**: Pipeline für hochauflösende Cover-Downloads und Einbettung in Dateien implementieren.  

### Erweiterte Features
- **Metadata Enhancement**: Beets-Integration um Tagging + Album Art erweitern; Felder validieren.  
- **Automatic Lyrics (LRC)**: Lyrics-Service anbinden, LRC-Dateien speichern und mit Downloads verknüpfen.  
- **Auto Server Scanning**: Plex-Refresh nach jedem erfolgreichen Download automatisch anstoßen.  
- **Auto Database Updates**: Soulseek-/Beets-Synchronisation erweitern, damit Datenbankeinträge nach Imports aktualisiert werden.  
- **File Organization**: Eigene Logik für strukturierte Ordner/Umbenennung ergänzen (nicht nur Beets).  
- **Artist Discovery**: API und UI für das Durchstöbern kompletter Diskografien.  
- **Wishlist System**: API + UI, die fehlgeschlagene Downloads (`auto_sync_skipped_tracks`) anzeigt und manuelles Retry erlaubt.  
- **Artist Watchlist**: System zum Überwachen neuer Releases inkl. Benachrichtigung und automatischem Ergänzen fehlender Tracks.  
- **Background Automation**: Retry-Mechanismus erweitern → fehlgeschlagene Downloads stündlich erneut versuchen (nicht nur max. 3 Retries).

---

## 🏁 Nächste Meilensteine
1. **Beets-Router** ins Haupt-Backend einbinden (aktuell nur lokal nutzbar).  
2. **Smart Search** mit Filteroptionen erweitern.  
3. **Lyrics-Pipeline** als neues Feature starten.  
4. **Wishlist/Watchlist-System** entwerfen und implementieren.  
5. **UI-Integration** für alle neuen Features (Spotify/Plex/Soulseek Settings, Lyrics, Discovery, Wishlist).
