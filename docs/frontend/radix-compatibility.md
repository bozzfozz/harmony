# Radix UI Compatibility Matrix (archiviert)

Die frühere Vite-/React-Oberfläche wurde zugunsten eines buildlosen ES-Module-Frontends entfernt. Das aktuelle UI verwendet keine Radix-Komponenten mehr. Dieses Dokument bleibt als Hinweis bestehen, dass neue Abhängigkeiten als statische ES-Module unter `frontend-static/js/` gepflegt werden und CDN-Ressourcen direkt in den HTML-Dateien mit Versions-Pin und SRI eingebunden werden müssen.

## Frontend-Richtlinien

- Neue UI-Komponenten werden als native ES-Module unter `frontend-static/js/` implementiert; CDN-Bibliotheken dürfen nur mit festen Versionsangaben und SRI-Hashes eingebunden werden.
- Zusätzliche Build-Schritte oder Vendoring-Skripte sind nicht mehr erforderlich.
