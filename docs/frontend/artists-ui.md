# Artist Watchlist & Detail UI

Die neue Artist-Oberfläche ist unter `/artists` erreichbar und bündelt Watchlist, Detailansicht, Match-Kuration sowie Sync-Aktionen in einem konsistenten Workflow.

## Watchlist (`/artists`)

- Reaktive Tabelle mit Suchfeld und Filtern für Priorität und Gesundheitsstatus.
- Inline-Aktionen pro Artist: Priorität, Sync-Intervall, Details, Entfernen.
- Hinzufügen-Formular für Spotify-Artist-ID + Name mit Validierung und Toast-Feedback.
- Badge-Highlights für offene Matches; Navigation zur Detailseite mit einem Klick.

## Detailansicht (`/artists/:id`)

- Header mit externen IDs, letztem Sync und direktem Zugriff auf Resync/Invalidate.
- Tabs: **Overview** (Health & Watchlist), **Releases** (filterbar nach Typ), **Matches** (Accept/Reject mit Status-Badges), **Activity** (chronologisches Log mit ScrollArea).
- Queue-Panel mit Status, Versuchen, ETA und Triggern (Bestätigung via Dialog).
- Regelmäßiges Polling (20 s) für den Sync-/Queue-Status.

## UX & Technik

- Shadcn/Radix-Komponenten (Tabs, Select, ScrollArea, Toast) und Tailwind-Theme (Dark/Light).
- React-Query-ähnlicher Client für Caching/Refetch (`src/lib/query`).
- API-Services: `listArtists`, `getArtistDetail`, `updateWatchlistEntry`, `updateArtistMatchStatus`, `enqueueArtistResync`, `invalidateArtistCache`.
- Tests (Jest + RTL): Routing, Watchlist-Interaktionen, Match-Aktionen, Queue-Polling, A11y-Rollen.

Siehe Implementierung in `frontend/src/pages/Artists/` und `frontend/src/api/services/artists.ts` für Details zu Komponenten und Parsing.
