type HttpMethod = 'GET' | 'POST';

interface MockRequest {
  method: HttpMethod;
  url: URL;
  json: () => Promise<any>;
}

interface MockResponse {
  status?: number;
  json?: unknown;
}

type HandlerResolver = (req: MockRequest) => Promise<MockResponse> | MockResponse;

interface Handler {
  method: HttpMethod;
  url: string;
  resolver: HandlerResolver;
}

const createJsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' }
  });

const mockGet = (url: string, resolver: HandlerResolver): Handler => ({ method: 'GET', url, resolver });
const mockPost = (url: string, resolver: HandlerResolver): Handler => ({ method: 'POST', url, resolver });

const initialSettings = {
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

let settingsState = { ...initialSettings };

export const resetSettings = () => {
  settingsState = { ...initialSettings };
};

const baseUrls = ['http://localhost', 'http://localhost:8000'];

const SERVICE_KEYS = {
  spotify: {
    required: ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET', 'SPOTIFY_REDIRECT_URI'],
    optional: []
  },
  plex: {
    required: ['PLEX_BASE_URL', 'PLEX_TOKEN'],
    optional: ['PLEX_LIBRARY']
  },
  soulseek: {
    required: ['SLSKD_URL'],
    optional: ['SLSKD_API_KEY']
  }
} as const;

type ServiceName = keyof typeof SERVICE_KEYS;

const isMissing = (value: unknown) =>
  value === null || value === undefined || (typeof value === 'string' && value.trim() === '');

const evaluateHealth = (service: ServiceName) => {
  const { required, optional } = SERVICE_KEYS[service];
  const missing = required.filter((key) => isMissing(settingsState[key]));
  const optionalMissing = optional.filter((key) => isMissing(settingsState[key]));
  return {
    service,
    status: missing.length === 0 ? 'ok' : 'fail',
    missing,
    optional_missing: optionalMissing
  };
};

const createBaseHandlers = (base: string): Handler[] => [
  mockGet(`${base}/`, () => ({ json: { status: 'ok', version: '1.4.0' } })),
  mockGet(`${base}/settings`, () => ({
    json: { settings: settingsState, updated_at: new Date('2024-03-01T12:00:00Z').toISOString() }
  })),
  mockPost(`${base}/settings`, async (req) => {
    const body = await req.json();
    settingsState[body.key] = body.value ?? null;
    return { json: { settings: settingsState, updated_at: new Date().toISOString() } };
  }),
  mockGet(`${base}/spotify/status`, () => ({ json: { status: 'connected' } })),
  mockGet(`${base}/spotify/playlists`, () => ({
    json: {
      playlists: [
        { id: '1', name: 'Daily Mix', track_count: 25, updated_at: '2024-03-01T10:00:00Z' },
        { id: '2', name: 'Workout', track_count: 40, updated_at: '2024-02-28T18:30:00Z' }
      ]
    }
  })),
  mockGet(`${base}/spotify/search/tracks`, (req) => {
    const query = req.url.searchParams.get('query') ?? '';
    if (!query) {
      return { json: { items: [] } };
    }
    return {
      json: {
        items: [
          {
            name: `Track ${query}`,
            artists: [{ name: 'Artist A' }],
            album: { name: 'Album X' }
          }
        ]
      }
    };
  }),
  mockGet(`${base}/plex/status`, () => ({
    json: {
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
    }
  })),
  mockGet(`${base}/soulseek/status`, () => ({ json: { status: 'connected' } })),
  mockGet(`${base}/soulseek/downloads`, () => ({
    json: {
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
    }
  })),
  mockPost(`${base}/soulseek/search`, async (req) => {
    const body = await req.json();
    if (!body.query) {
      return { json: { results: [] } };
    }
    return {
      json: {
        results: [
          {
            filename: `${body.query}.mp3`,
            username: 'SoulUser'
          }
        ]
      }
    };
  }),
  mockGet(`${base}/api/health/spotify`, () => ({ json: evaluateHealth('spotify') })),
  mockGet(`${base}/api/health/plex`, () => ({ json: evaluateHealth('plex') })),
  mockGet(`${base}/api/health/soulseek`, () => ({ json: evaluateHealth('soulseek') })),
  mockGet(`${base}/status`, () => ({
    json: {
      status: 'ok',
      version: '1.4.0',
      uptime_seconds: 12.5,
      connections: {
        spotify: evaluateHealth('spotify').status,
        plex: evaluateHealth('plex').status,
        soulseek: evaluateHealth('soulseek').status
      },
      workers: {
        sync: { status: 'running', last_seen: '2024-03-01T11:59:30Z', queue_size: 2 }
      }
    }
  }))
];

const defaultHandlers: Handler[] = baseUrls.flatMap((base) => createBaseHandlers(base));

const createServer = (handlers: Handler[]) => {
  let activeHandlers = [...handlers];
  let originalFetch: typeof fetch | undefined;

  const findHandler = (method: string, url: string) =>
    activeHandlers.find((handler) => handler.method === method && handler.url === url);

  return {
    listen: () => {
      originalFetch = global.fetch;
      global.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const requestUrl =
          typeof input === 'string'
            ? new URL(input)
            : input instanceof URL
              ? new URL(input.toString())
              : new URL((input as Request).url);
        const method = (
          init?.method ?? (typeof input === 'object' && 'method' in (input as Request) ? (input as Request).method : 'GET')
        ).toUpperCase();
        const handler = findHandler(method, requestUrl.toString());
        if (!handler) {
          throw new Error(`Unhandled request for ${method} ${requestUrl.toString()}`);
        }
        const resolverResult = await handler.resolver({
          method: handler.method,
          url: requestUrl,
          json: async () => {
            const body = init?.body;
            if (!body) {
              return {};
            }
            return typeof body === 'string' ? JSON.parse(body) : body;
          }
        });
        const status = resolverResult.status ?? 200;
        if (resolverResult.json !== undefined) {
          return createJsonResponse(resolverResult.json, status);
        }
        return new Response(null, { status });
      };
    },
    close: () => {
      if (originalFetch) {
        global.fetch = originalFetch;
      }
      activeHandlers = [...handlers];
    },
    resetHandlers: () => {
      activeHandlers = [...handlers];
    },
    use: (...newHandlers: Handler[]) => {
      activeHandlers = [...activeHandlers, ...newHandlers];
    }
  };
};

export const server = createServer(defaultHandlers);
export const rest = { get: mockGet, post: mockPost };
