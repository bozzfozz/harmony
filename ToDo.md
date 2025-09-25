# ToDo

## Abgeschlossen
- [x] Frontend auf vier Kernseiten (Dashboard, Downloads, Artists, Settings) konsolidiert.
- [x] Zentralen API-Client mit globalem Fehler-Handling und Toast-Routing etabliert.
- [x] Dashboard-Karten für Service-Status, Worker-Zustand und Activity Feed vereinheitlicht.
- [x] Frontend-Tests für Dashboard, Downloads, Artists und Settings aktualisiert.
- [x] Design-Guidelines dokumentiert und im UI angewendet.
- [x] Release-Filter (Album/Single/EP) auf der Artists-Seite ergänzt.

## Offen
- [ ] Integrationstests für globale API-Fehler (401/403/503) inklusive Redirect-Checks ergänzen.
- [ ] `npm run test` auf reale Testausführung (Jest/Vitest) umstellen.
- [ ] Accessibility-Audit der vier Kernseiten (Keyboard-Navigation, ARIA, Farbkontrast) durchführen.
- [ ] Automatisierte Screenshot-Generierung für `docs/screenshots/*.svg` aus dem Frontend einführen.
- [ ] TypeScript-Typen aus dem OpenAPI-Schema generieren und in den API-Client integrieren.
- [ ] Observability-Anbindung (Prometheus/StatsD) vorbereiten, um Worker- und Download-Kennzahlen zu erfassen.
