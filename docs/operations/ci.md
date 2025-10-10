# CI-Pipeline-Überblick

## OpenAPI-Snapshot-Job

- Startet einen PostgreSQL-Service (`postgres:16`) mit identischen Datenbankparametern wie der `backend`-Job.
- Exportiert `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/harmony`, damit das Schema-Tooling auf die Datenbank zugreift.
- Enthält eine Warte-Schleife (`pg_isready` bis zu 30 Versuche), damit der Datenbankdienst erreichbar ist, bevor der Snapshot-Vergleich läuft.
- Führt anschließend das Snapshot-Skript aus, das das zur Laufzeit generierte OpenAPI-Schema mit `tests/snapshots/openapi.json` vergleicht.

## Status & Verifizierung

- Änderungen sind in `.github/workflows/ci.yml` hinterlegt (Job `openapi`).
- Ein lokaler Lauf mit `act` scheitert derzeit an fehlender Unterstützung in der Standardumgebung; in GitHub Actions wird der Job mit dem neuen Datenbankkontext ausgeführt.
- Der Job `ci-frontend` veröffentlicht das gebaute `frontend/dist`-Verzeichnis als Artefakt `frontend-dist`. Lade dieses Paket herunter, um Deployments ohne erneuten lokalen Build anzustoßen oder die ausgelieferte `env.runtime.js` zu inspizieren.
