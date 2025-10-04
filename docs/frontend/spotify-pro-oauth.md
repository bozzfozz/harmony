# Spotify PRO OAuth UX

Die Spotify-Seite führt Administrator:innen jetzt durch den kompletten PRO-OAuth-Fluss, ohne dass ein manueller Wechsel ins Backend nötig ist.

## Ablauf

1. **Statusprüfung:** Beim Öffnen der Seite wird `GET /spotify/status` aufgerufen und der aktuelle Authentifizierungszustand angezeigt. Buttons für PRO-Funktionen bleiben deaktiviert, solange keine gültigen Credentials hinterlegt sind.
2. **OAuth-Start:** Ein Klick auf „Watchlist öffnen“ oder „Künstlerbibliothek“ startet `POST /spotify/pro/oauth/start`. Das Frontend erzeugt bzw. übernimmt den State-Parameter, persistiert ihn in der Session und öffnet ein OAuth-Popup. Fällt das Popup durch einen Blocker aus, wird ein manueller Link eingeblendet.
3. **Status-Polling:** Während des Logins pollt die Seite `GET /spotify/pro/oauth/status` (inklusive State) und reagiert zusätzlich auf `postMessage`-Events der Callback-Seite (`/spotify/oauth/callback`). Das Polling endet bei `authorized`, `failed` oder `cancelled`.
4. **Session-Refresh:** Nach einem erfolgreichen Abschluss ruft das Frontend `POST /spotify/pro/oauth/session` auf. Schlägt der Refresh fehl, erfolgt ein stilles Re-Fetch von `GET /spotify/status`.
5. **Feedback:**
   - Bei Erfolg erscheint ein Dialog mit Links zur Watchlist, Künstlerbibliothek und den Backfill-Aufträgen. Der zuvor gewählte Button wird hervorgehoben.
   - Bei Fehlern oder einem Abbruch erhält die Benutzeroberfläche einen Hinweis und die Buttons bleiben deaktiviert, bis ein neuer Versuch gestartet wird.

## Callback-Seite

- Der Backend-Redirect verweist auf `/spotify/oauth/callback`. Diese Seite sendet `postMessage` (Quelle `harmony.spotify.pro.oauth`) an das Hauptfenster, zeigt den aktuellen Status an und schließt sich nach erfolgreicher Anmeldung automatisch.
- Das Callback prüft den State-Wert gegen die Session, damit der Flow nicht durch fremde Nachrichten beeinflusst werden kann.

## Testing

Unit-Tests in `frontend/src/__tests__/SpotifyPage.test.tsx` mocken Start-, Status- und Refresh-Endpunkte, um Erfolgs-, Fehler- und Abbruchfälle abzudecken.
