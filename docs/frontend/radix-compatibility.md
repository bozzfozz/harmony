# Radix UI Compatibility Matrix (archiviert)

Die frühere Vite-/React-Oberfläche wurde zugunsten eines buildlosen ES-Module-Frontends entfernt. Das aktuelle UI verwendet keine Radix-Komponenten mehr. Dieses Dokument bleibt als Hinweis bestehen, dass neue Abhängigkeiten direkt über die Import-Map (`frontend/importmap.json`) oder den optionalen Vendoring-Workflow gepflegt werden müssen.

## Frontend-Richtlinien

- Neue UI-Komponenten werden als native ES-Module implementiert; Bibliotheken werden per Import-Map referenziert.
- Versionen müssen in der Import-Map mit festen Pins (`@x.y.z`) hinterlegt sein.
- Für Offline-Betrieb `scripts/dev/vendor_frontend.sh` ausführen und die Import-Map auf lokale Pfade rewriten lassen.
