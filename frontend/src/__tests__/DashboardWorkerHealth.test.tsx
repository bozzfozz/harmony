import { act, screen, waitFor, within } from '@testing-library/react';
import Dashboard from '../pages/Dashboard';
import { renderWithProviders } from '../test-utils';
import {
  fetchBeetsStats,
  fetchPlexLibraries,
  fetchPlexStatus,
  fetchSoulseekDownloads,
  fetchSoulseekStatus,
  fetchSpotifyPlaylists,
  fetchSpotifyStatus,
  fetchSystemStatus
} from '../lib/api';

jest.mock('../lib/api', () => ({
  fetchBeetsStats: jest.fn(),
  fetchPlexLibraries: jest.fn(),
  fetchPlexStatus: jest.fn(),
  fetchSoulseekDownloads: jest.fn(),
  fetchSoulseekStatus: jest.fn(),
  fetchSpotifyPlaylists: jest.fn(),
  fetchSpotifyStatus: jest.fn(),
  fetchSystemStatus: jest.fn()
}));

const toastMock = jest.fn();
const fixedNow = new Date('2025-01-01T12:00:00Z').getTime();

const resolveDefaultQueries = () => {
  (fetchSpotifyStatus as jest.Mock).mockResolvedValue({ status: 'ok' });
  (fetchSpotifyPlaylists as jest.Mock).mockResolvedValue([]);
  (fetchPlexStatus as jest.Mock).mockResolvedValue({ status: 'ok' });
  (fetchPlexLibraries as jest.Mock).mockResolvedValue({});
  (fetchSoulseekStatus as jest.Mock).mockResolvedValue({ status: 'ok' });
  (fetchSoulseekDownloads as jest.Mock).mockResolvedValue([]);
  (fetchBeetsStats as jest.Mock).mockResolvedValue({ stats: {} });
};

describe('Dashboard worker health', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Date, 'now').mockReturnValue(fixedNow);
    resolveDefaultQueries();
    (fetchSystemStatus as jest.Mock).mockResolvedValue({
      status: 'ok',
      workers: {
        sync: {
          status: 'running',
          last_seen: '2025-01-01T11:59:30Z',
          queue_size: 2
        },
        autosync: {
          status: 'stopped',
          last_seen: null,
          queue_size: 'n/a'
        }
      }
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it('renders worker health cards from system status', async () => {
    renderWithProviders(<Dashboard />, { toastFn: toastMock });

    expect(await screen.findByText('Worker Health')).toBeInTheDocument();
    const syncCard = await screen.findByTestId('worker-card-sync');
    expect(within(syncCard).getByText('Sync')).toBeInTheDocument();
    expect(within(syncCard).getByText('vor 30s')).toBeInTheDocument();
    const autosyncCard = await screen.findByTestId('worker-card-autosync');
    expect(within(autosyncCard).getByText('Autosync')).toBeInTheDocument();
  });

  it('polls the system status every 10 seconds', async () => {
    jest.useFakeTimers();
    renderWithProviders(<Dashboard />, { toastFn: toastMock });

    await waitFor(() => expect(fetchSystemStatus).toHaveBeenCalledTimes(1));

    await act(async () => {
      jest.advanceTimersByTime(10000);
    });

    await waitFor(() => expect(fetchSystemStatus).toHaveBeenCalledTimes(2));
  });

  it('shows a toast when fetching the system status fails', async () => {
    (fetchSystemStatus as jest.Mock).mockRejectedValue(new Error('offline'));

    renderWithProviders(<Dashboard />, { toastFn: toastMock });

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Failed to load worker status' })
      )
    );
  });
});
