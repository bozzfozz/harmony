import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';

import ArtistDetailPage from '../pages/Artists/ArtistDetailPage';
import { renderWithProviders } from '../test-utils';
import {
  enqueueArtistResync,
  getArtistDetail,
  invalidateArtistCache,
  updateArtistMatchStatus
} from '../api/services/artists';

jest.mock('../api/services/artists', () => ({
  ...jest.requireActual('../api/services/artists'),
  getArtistDetail: jest.fn(),
  enqueueArtistResync: jest.fn(),
  invalidateArtistCache: jest.fn(),
  updateArtistMatchStatus: jest.fn()
}));

const mockedGetArtistDetail = getArtistDetail as jest.MockedFunction<typeof getArtistDetail>;
const mockedEnqueueResync = enqueueArtistResync as jest.MockedFunction<typeof enqueueArtistResync>;
const mockedInvalidateCache = invalidateArtistCache as jest.MockedFunction<typeof invalidateArtistCache>;
const mockedUpdateMatchStatus = updateArtistMatchStatus as jest.MockedFunction<typeof updateArtistMatchStatus>;

const createDetailResponse = () => ({
  artist: {
    id: 'artist-1',
    name: 'First Artist',
    external_ids: { spotify: 'spotify:artist:1' },
    watchlist: {
      id: 'watch-1',
      enabled: true,
      priority: 'medium',
      interval_days: 7,
      last_synced_at: '2024-05-01T10:00:00Z',
      next_sync_at: '2024-05-08T10:00:00Z'
    },
    health_status: 'ok',
    releases_total: 2,
    matches_pending: 1,
    updated_at: '2024-05-02T10:00:00Z'
  },
  releases: [
    {
      id: 'rel-1',
      title: 'Album A',
      type: 'album',
      released_at: '2024-01-10T00:00:00Z',
      spotify_url: 'https://example.com'
    }
  ],
  matches: [
    {
      id: 'match-1',
      title: 'Track X',
      confidence: 0.82,
      release_title: 'Album A',
      provider: 'Spotify',
      status: 'pending',
      badges: [{ label: 'Neu', tone: 'info' }],
      submitted_at: '2024-05-03T12:00:00Z'
    }
  ],
  activity: [
    {
      id: 'act-1',
      created_at: '2024-05-02T11:00:00Z',
      message: 'Sync abgeschlossen',
      category: 'sync',
      meta: null
    }
  ],
  queue: {
    status: 'running',
    attempts: 1,
    eta: '2024-05-06T12:00:00Z'
  }
});

describe('ArtistDetailPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetArtistDetail.mockResolvedValue(createDetailResponse());
    mockedEnqueueResync.mockResolvedValue();
    mockedInvalidateCache.mockResolvedValue();
    mockedUpdateMatchStatus.mockResolvedValue();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('zeigt Artist-Details und Tabs an', async () => {
    renderWithProviders(<ArtistDetailPage />, { route: '/artists/artist-1' });

    expect(await screen.findByText('Sync-Aktionen')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'First Artist', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('data-state', 'active');
    expect(mockedGetArtistDetail).toHaveBeenCalledWith('artist-1');
  });

  it('ermöglicht Match-Aktionen sowie Resync und Cache-Invalidierung', async () => {
    const toastSpy = jest.fn();
    const resyncConfirm = jest.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<ArtistDetailPage />, { route: '/artists/artist-1', toastFn: toastSpy });

    await screen.findByText('Track X');

    await userEvent.click(screen.getByRole('button', { name: /Accept/i }));
    await waitFor(() =>
      expect(mockedUpdateMatchStatus).toHaveBeenCalledWith('artist-1', 'match-1', 'accept')
    );

    await userEvent.click(screen.getByRole('button', { name: 'Resync' }));
    await waitFor(() => expect(mockedEnqueueResync).toHaveBeenCalledWith('artist-1'));

    await userEvent.click(screen.getByRole('button', { name: 'Invalidate Cache' }));
    await waitFor(() => expect(mockedInvalidateCache).toHaveBeenCalledWith('artist-1'));

    expect(toastSpy).toHaveBeenCalled();
    resyncConfirm.mockRestore();
  });

  it('pollt den Queue-Status in Intervallen', async () => {
    jest.useFakeTimers();
    renderWithProviders(<ArtistDetailPage />, { route: '/artists/artist-1' });

    await screen.findByText('Track X');
    mockedGetArtistDetail.mockClear();

    jest.advanceTimersByTime(20000);

    await waitFor(() => expect(mockedGetArtistDetail).toHaveBeenCalled());
    jest.useRealTimers();
  });
});
