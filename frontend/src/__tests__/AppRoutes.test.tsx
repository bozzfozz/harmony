import { screen } from '@testing-library/react';

import AppRoutes from '../routes';
import { renderWithProviders } from '../test-utils';
import {
  getIntegrations,
  getSoulseekConfiguration,
  getSoulseekStatus,
  getSoulseekUploads
} from '../api/services/soulseek';
import { getMatchingOverview } from '../api/services/matching';
import { getArtistDetail, listArtists } from '../api/services/artists';

jest.mock('../api/services/soulseek', () => ({
  getSoulseekStatus: jest.fn(),
  getSoulseekUploads: jest.fn(),
  getIntegrations: jest.fn(),
  getSoulseekConfiguration: jest.fn()
}));

jest.mock('../api/services/matching', () => ({
  getMatchingOverview: jest.fn()
}));

jest.mock('../api/services/artists', () => ({
  ...jest.requireActual('../api/services/artists'),
  listArtists: jest.fn(),
  getArtistDetail: jest.fn()
}));

const mockedGetSoulseekStatus = getSoulseekStatus as jest.MockedFunction<typeof getSoulseekStatus>;
const mockedGetSoulseekUploads = getSoulseekUploads as jest.MockedFunction<typeof getSoulseekUploads>;
const mockedGetIntegrations = getIntegrations as jest.MockedFunction<typeof getIntegrations>;
const mockedGetSoulseekConfiguration = getSoulseekConfiguration as jest.MockedFunction<
  typeof getSoulseekConfiguration
>;
const mockedGetMatchingOverview = getMatchingOverview as jest.MockedFunction<typeof getMatchingOverview>;
const mockedListArtists = listArtists as jest.MockedFunction<typeof listArtists>;
const mockedGetArtistDetail = getArtistDetail as jest.MockedFunction<typeof getArtistDetail>;

describe('AppRoutes', () => {
  const renderWithRoute = (route: string) => renderWithProviders(<AppRoutes />, { route });

  beforeEach(() => {
    mockedGetSoulseekStatus.mockResolvedValue({ status: 'connected' });
    mockedGetSoulseekUploads.mockResolvedValue([]);
    mockedGetIntegrations.mockResolvedValue({ overall: 'ok', providers: [] });
    mockedGetSoulseekConfiguration.mockResolvedValue([]);
    mockedGetMatchingOverview.mockResolvedValue({
      worker: { status: 'running', lastSeen: '2024-05-05T10:00:00Z', queueSize: 0, rawQueueSize: 0 },
      metrics: {
        lastAverageConfidence: 0.92,
        lastDiscarded: 0,
        savedTotal: 12,
        discardedTotal: 3
      },
      events: []
    });
    mockedListArtists.mockResolvedValue({ items: [], total: 0, page: 1, per_page: 25 });
    mockedGetArtistDetail.mockResolvedValue({
      artist: {
        id: 'artist-42',
        name: 'Test Artist',
        watchlist: {
          id: 'watch-42',
          enabled: true,
          priority: 'medium',
          interval_days: 7,
          last_synced_at: null,
          next_sync_at: null
        },
        health_status: 'ok',
        releases_total: 0,
        matches_pending: 0,
        updated_at: null
      },
      releases: [],
      matches: [],
      activity: [],
      queue: { status: 'idle', attempts: 0, eta: null }
    });
  });

  it('renders the Soulseek page without redirecting', async () => {
    renderWithRoute('/soulseek');

    expect(screen.getByRole('heading', { name: /Soulseek/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/Verbindung wird geprüft/i)).toBeInTheDocument();
    expect(await screen.findByText(/Aktive Uploads/i)).toBeInTheDocument();
  });

  it('renders the Matching page without redirecting', async () => {
    renderWithRoute('/matching');

    expect(
      screen.getByRole('heading', { name: /Matching/i, level: 1 })
    ).toBeInTheDocument();
    expect(await screen.findByText('Worker-Status')).toBeInTheDocument();
    expect(screen.getByText(/Ø Konfidenz/)).toBeInTheDocument();
    expect(screen.getByText(/Noch keine Matching-Läufe/)).toBeInTheDocument();
  });

  it('rendert die Artists-Route ohne Redirect', async () => {
    renderWithRoute('/artists');

    expect(await screen.findByRole('heading', { name: 'Artist Watchlist' })).toBeInTheDocument();
    expect(mockedListArtists).toHaveBeenCalled();
  });

  it('rendert die Artist-Detail-Route', async () => {
    renderWithRoute('/artists/artist-42');

    expect(await screen.findByText('Sync-Aktionen')).toBeInTheDocument();
    expect(mockedGetArtistDetail).toHaveBeenCalledWith('artist-42');
  });
});
