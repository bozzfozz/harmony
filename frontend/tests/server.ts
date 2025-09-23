import { rest } from 'msw';
import { setupServer } from 'msw/node';

interface SettingsState {
  [key: string]: string | null;
}

const initialSettings: SettingsState = {
  SPOTIFY_CLIENT_ID: 'client-id',
  SPOTIFY_CLIENT_SECRET: 'client-secret',
  SPOTIFY_REDIRECT_URI: 'http://localhost/callback',
  PLEX_BASE_URL: 'http://plex.local',
  PLEX_TOKEN: 'plex-token',
  PLEX_LIBRARY: 'Music',
  SLSKD_URL: 'http://slskd.local',
  SLSKD_API_KEY: 'secret',
  BEETS_LIBRARY_PATH: '/music/beets',
  BEETS_IMPORT_TARGET: '/music/import'
};

let settingsState: SettingsState = { ...initialSettings };

export const resetSettings = () => {
  settingsState = { ...initialSettings };
};

const base = 'http://localhost';

export const handlers = [
  rest.get(`${base}/`, (_req, res, ctx) =>
    res(ctx.json({ status: 'ok', version: '1.4.0' }))
  ),
  rest.get(`${base}/settings`, (_req, res, ctx) =>
    res(ctx.json({ settings: settingsState, updated_at: new Date('2024-03-01T12:00:00Z').toISOString() }))
  ),
  rest.post(`${base}/settings`, async (req, res, ctx) => {
    const body = (await req.json()) as { key: string; value: string | null };
    settingsState[body.key] = body.value ?? null;
    return res(ctx.json({ settings: settingsState, updated_at: new Date().toISOString() }));
  }),
  rest.get(`${base}/spotify/status`, (_req, res, ctx) => res(ctx.json({ status: 'connected' }))),
  rest.get(`${base}/spotify/playlists`, (_req, res, ctx) =>
    res(
      ctx.json({
        playlists: [
          { id: '1', name: 'Daily Mix', track_count: 25, updated_at: '2024-03-01T10:00:00Z' },
          { id: '2', name: 'Workout', track_count: 40, updated_at: '2024-02-28T18:30:00Z' }
        ]
      })
    )
  ),
  rest.get(`${base}/spotify/search/tracks`, (req, res, ctx) => {
    const query = req.url.searchParams.get('query') ?? '';
    if (!query) {
      return res(ctx.json({ items: [] }));
    }
    return res(
      ctx.json({
        items: [
          {
            name: `Track ${query}`,
            artists: [{ name: 'Artist A' }],
            album: { name: 'Album X' }
          }
        ]
      })
    );
  }),
  rest.get(`${base}/plex/status`, (_req, res, ctx) =>
    res(
      ctx.json({
        status: 'connected',
        library: { artists: 2, albums: 3, tracks: 5 },
        sessions: {
          MediaContainer: {
            Metadata: [
              {
                sessionKey: 'abc',
                title: 'Song Title',
                user: { title: 'Alice' },
                type: 'track'
              }
            ]
          }
        }
      })
    )
  ),
  rest.get(`${base}/soulseek/status`, (_req, res, ctx) => res(ctx.json({ status: 'connected' }))),
  rest.get(`${base}/soulseek/downloads`, (_req, res, ctx) =>
    res(
      ctx.json({
        downloads: [
          {
            id: 1,
            filename: 'Artist - Song.mp3',
            state: 'running',
            progress: 45,
            created_at: '2024-03-01T09:00:00Z',
            updated_at: '2024-03-01T09:15:00Z'
          },
          {
            id: 2,
            filename: 'Album.zip',
            state: 'queued',
            progress: 0,
            created_at: '2024-03-01T08:30:00Z',
            updated_at: '2024-03-01T08:30:00Z'
          }
        ]
      })
    )
  ),
  rest.post(`${base}/soulseek/search`, async (req, res, ctx) => {
    const body = (await req.json()) as { query: string };
    if (!body.query) {
      return res(ctx.json({ results: [] }));
    }
    return res(
      ctx.json({
        results: [
          {
            filename: `${body.query}.mp3`,
            username: 'SoulUser'
          }
        ]
      })
    );
  })
];

export const server = setupServer(...handlers);
