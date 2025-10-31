# Backend Architecture & Development Guidelines

Diese Guidelines definieren Standards für den Aufbau und die Pflege von Backend-Systemen. Sie sind neutral formuliert und können in jedem Projekt angewendet werden.

## 1. Architekturprinzipien
- **Schichtenmodell**  
  - Core: Anbindung externer Systeme (APIs, Datenbanken, Infrastruktur).  
  - Services: Business-Logik, unabhängig vom Web-Framework.  
  - Routers/Controllers: nur Request → Service → Response.  
  - Workers: Hintergrundprozesse.  
  - Models/Schemas: Datenbank- und API-Modelle.  
- **Import-Regeln**: Keine zirkulären Abhängigkeiten; nur „unten → oben“ (Core → Services → Routers).  
- **Single Responsibility**: Jede Datei und jedes Modul erfüllt genau eine Aufgabe.  

## 2. FastAPI Best Practices
- Modularisierung: Jeder Funktionsbereich bekommt einen eigenen Router.  
- Dependencies (`Depends`) statt globaler States.  
- Request-/Response-Validierung ausschließlich mit Pydantic.  
- Fehlerbehandlung konsistent mit `HTTPException`.  
- Business-Logik gehört in Services, nicht in Router-Funktionen.  

## 3. Twelve-Factor App Prinzipien (angepasst)
1. **Config**: Konfiguration über Umgebungsvariablen oder Settings-Dateien, niemals fest im Code.  
2. **Dependencies**: Alle Abhängigkeiten deklarieren (`uv.lock`, `pyproject.toml`).
3. **Logs**: Strukturierte Logs mit Leveln (`INFO`, `ERROR`, `DEBUG`), keine `print()`.  
4. **Disposability**: Prozesse (inkl. Worker) müssen sauber starten und stoppen können.  
5. **Dev/Prod parity**: Entwicklungsumgebung soll Produktionsumgebung möglichst ähneln (z. B. Docker).  

## 4. Datenbank / Persistenz
- Nutzung von Sessions und Transaktionen (z. B. SQLAlchemy Session).  
- Indizes für häufig verwendete Filterspalten setzen.  
- Schema-Änderungen über SQLAlchemy-Models kapseln; `Base.metadata.create_all()` hält SQLite-Schemata synchron.
- Kein direkter SQL-String-Zugriff in Routern oder Services.  

## 5. Sicherheit (OWASP API Top 10 Light)
- **Authentifizierung**: Alle Endpunkte sind geschützt (API-Key, OAuth, JWT).  
- **Input Validation**: Validierung von Daten über Pydantic-Schemas.  
- **Least Privilege**: Externe Systeme nur mit minimal nötigen Rechten anbinden.  
- **Error Handling**: Keine internen Stacktraces in API-Responses.  
- **Rate Limiting**: Schutz vor Missbrauch durch Drosselung.  

## 6. Monitoring & Observability
- **Status-Endpoints** bereitstellen (`/status`, `/health`, `/ready`).
- **Systemmetriken** sammeln (CPU, RAM, Disk, Netzwerk).  
- **Audit-Logs/Activity Feed** für nachvollziehbare Änderungen pflegen.  
- **Logs** strukturiert ausgeben und optional in Systeme wie Prometheus, Grafana, ELK weiterleiten.  

## 7. Testing & lokale Gates
- Unit-Tests für Services und Core-Clients.  
- API-Tests für Router-Endpunkte (Happy Path + Fehlerfälle).  
- Worker-Tests mit Queue-Simulationen.  
- Integration-Tests (End-to-End-Flows).  
- `scripts/dev/test_py.sh` bzw. `uv run pytest -q` und `uv run pip-audit --strict` laufen vor jedem Merge lokal; `uv run make all` bündelt optionale Zusatzprüfungen.

## 8. Dokumentation
- API-Endpunkte mit Beispielen dokumentieren (Markdown, OpenAPI).
- Architekturübersicht (Schichten, Hauptmodule).
- Worker-Dokumentation (Aufgabe, Intervalle, Fehlerbehandlung).
- Changelog nach [Keep a Changelog](https://keepachangelog.com/).

## 9. Linting & Formatting
- Vor jedem Commit sind die Python-Gates (`ruff format --check`, `ruff check --output-format=github`, `mypy`, `pytest`, `pip-audit`) lokal auszuführen.
- Finale Routine: `ruff format .`, `ruff check --select I --fix .`, anschließend `git diff --exit-code`. Ohne leeren Diff keine Doku-/CHANGELOG-/BACKUP-Schritte.
- Ruff übernimmt Formatierung & Imports; zusätzliche Formatierungen nur nach Abstimmung (keine stillen Massenformate).
- Verbleibende Hinweise (z. B. bewusst ungenutzte Importe) müssen manuell adressiert und dokumentiert werden (`# noqa`).

