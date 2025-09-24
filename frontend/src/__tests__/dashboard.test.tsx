import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Dashboard from '../pages/Dashboard';
import { renderWithProviders } from '../test-utils';

const toastMock = jest.fn();

const fetchSpotifyStatusMock = jest.fn();
const fetchSpotifyPlaylistsMock = jest.fn();
const fetchPlexStatusMock = jest.fn();
const fetchPlexLibrariesMock = jest.fn();
const fetchSoulseekStatusMock = jest.fn();
const fetchSoulseekDownloadsMock = jest.fn();
const fetchSystemStatusMock = jest.fn();
const fetchBeetsStatsMock = jest.fn();
const triggerSyncMock = jest.fn();

jest.mock('../lib/api', () => ({
  fetchSpotifyStatus: (...args: unknown[]) => fetchSpotifyStatusMock(...args),
  fetchSpotifyPlaylists: (...args: unknown[]) => fetchSpotifyPlaylistsMock(...args),
  fetchPlexStatus: (...args: unknown[]) => fetchPlexStatusMock(...args),
  fetchPlexLibraries: (...args: unknown[]) => fetchPlexLibrariesMock(...args),
  fetchSoulseekStatus: (...args: unknown[]) => fetchSoulseekStatusMock(...args),
  fetchSoulseekDownloads: (...args: unknown[]) => fetchSoulseekDownloadsMock(...args),
  fetchSystemStatus: (...args: unknown[]) => fetchSystemStatusMock(...args),
  fetchBeetsStats: (...args: unknown[]) => fetchBeetsStatsMock(...args),
  triggerSync: (...args: unknown[]) => triggerSyncMock(...args)
}));

beforeEach(() => {
  jest.clearAllMocks();
  fetchSpotifyStatusMock.mockResolvedValue({ status: 'connected', track_count: 0 });
  fetchSpotifyPlaylistsMock.mockResolvedValue([]);
  fetchPlexStatusMock.mockResolvedValue({ status: 'connected' });
  fetchPlexLibrariesMock.mockResolvedValue({});
  fetchSoulseekStatusMock.mockResolvedValue({ status: 'connected' });
  fetchSoulseekDownloadsMock.mockResolvedValue([]);
  fetchSystemStatusMock.mockResolvedValue({ connections: {}, workers: {} });
  fetchBeetsStatsMock.mockResolvedValue({ stats: {} });
  triggerSyncMock.mockResolvedValue(undefined);
});

describe('Dashboard', () => {
  it('shows toast on fetch error', async () => {
    fetchSpotifyStatusMock.mockRejectedValueOnce(new Error('network error'));

    renderWithProviders(<Dashboard />, { toastFn: toastMock });

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Failed to load Spotify status' })
      )
    );
  });

  it('shows blocked toast when sync endpoint returns 503', async () => {
    triggerSyncMock.mockRejectedValueOnce({ isAxiosError: true, response: { status: 503 } });

    renderWithProviders(<Dashboard />, { toastFn: toastMock });

    const button = await screen.findByRole('button', { name: 'Sync starten' });
    await userEvent.click(button);

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Sync blockiert' })
      )
    );
  });
});
