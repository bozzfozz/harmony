# ToDo

## ✅ Erledigt
- AGENTS.md aktualisiert (Task-Template-Pflicht & ToDo-Pflege etabliert)
- FastAPI-Anwendung mit Routern (Spotify, Plex, Soulseek, Matching, Beets, Settings)
- Worker-System (PlaylistSyncWorker, SyncWorker, MatchingWorker, ScanWorker, DiscographyWorker, MetadataWorker, ArtworkWorker, LyricsWorker, AutoSyncWorker)  
- Datenbank-Anbindung mit Session-Handling und Modellen  
- Spotify-Integration (Suche, Playlists, Audio-Features, Recommendations)  
- Concurrent Downloads mit Fortschritts-API  
- Retry-Logik mit Backoff (max. 3 Versuche)  
- Plex-Scan über ScanWorker inkl. inkrementeller Scans  
- Automatische Datenbank-Updates durch Worker  
- Beets-Integration (import, move, write, update)  
- AutoSync für Playlists und fehlende Tracks (inkl. FLAC-Priorität)  
- Matching-Engine für Spotify ↔ Plex/Soulseek  

---

## ⬜️ Offen
- **Smart Search** ⚠️  
  - Nur Aggregation von Spotify, Plex und Soulseek verfügbar.  
  - Filter für Genre, Jahr und Qualität fehlen.  

- **File Organization** ❌  
  - Keine eigene Logik für Umbenennung oder strukturierte Ordner.  
  - Aktuell nur Beets-Import.  

- **Artist Discovery** ❌  
  - Kein Router oder UI zum Browsen kompletter Diskografien.  

- **Wishlist System** ❌  
  - Fehlgeschlagene Downloads werden nicht persistent gespeichert.  
  - Keine API/Retry-Integration.  

- **Artist Watchlist** ❌  
  - Keine Überwachung neuer Releases implementiert.  

- **Background Automation** ❌  
  - Retry-Logik beschränkt auf max. 3 Backoff-Versuche.  
  - Kein stündliches Langzeit-Retry implementiert.  

---

## 🏁 Meilensteine
1. **Such-Filter erweitern** (Genre, Jahr, Qualität) → Smart Search verbessern  
2. **Eigene Dateiorganisation** entwickeln (strukturierte Ordner, benutzerdefinierte Patterns)  
3. **Artist Discovery**-Seite/API für komplettes Durchstöbern von Diskografien  
4. **Wishlist-System** aufbauen (fehlgeschlagene Downloads speichern, UI/Retry)  
5. **Artist Watchlist** implementieren (neue Releases überwachen, automatische Ergänzungen)  
6. **Background Automation** erweitern → stündliche Wiederholjobs für fehlgeschlagene Downloads
