# Harmony

## Schnellstart (Produktion)

1. **Verzeichnisse vorbereiten**

   Legen Sie die persistenten Verzeichnisse an und passen Sie deren Besitzrechte an die Benutzer- und Gruppenkonten an, unter denen der Container laufen soll:

   ```bash
   mkdir -p ./data/config ./data/downloads ./data/music
   chown -R ${PUID:-1000}:${PGID:-1000} ./data
   ```

   Die Anwendung legt ihre SQLite-Datenbank fest unter `/config/harmony.db` ab. Stellen Sie sicher, dass das `./data/config`-Verzeichnis für den gewählten `PUID`/`PGID` beschreibbar ist.

2. **Stack starten**

   ```bash
   docker compose up -d
   ```

   Der Dienst läuft im Hintergrund und verwendet die in `docker-compose.yml` definierten Umgebungsvariablen (einschließlich `PUID` und `PGID`) für sichere Zugriffsrechte.

3. **Gesundheit prüfen**

   Kontrollieren Sie den Zustand des Containers und die bereitgestellten Endpunkte, um sicherzustellen, dass der Dienst funktionsfähig ist:

   ```bash
   docker compose ps
   docker compose logs harmony
   curl http://localhost:8080/api/health
   ```

4. **Updates einspielen**

   Führen Sie bei neuen Versionen ein kontrolliertes Update durch:

   ```bash
   docker compose pull
   docker compose up -d
   docker image prune -f
   ```

   Alternativ können Sie bei lokalen Änderungen `docker compose build` voranstellen. Der Container migriert die Datenbank automatisch und behält bestehende Inhalte unter `/config/harmony.db` bei.

