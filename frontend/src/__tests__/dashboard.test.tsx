import { waitFor } from '@testing-library/react';
import Dashboard from '../pages/Dashboard';
import { renderWithProviders } from '../test-utils';

const toastMock = jest.fn();

jest.mock('../lib/api', () => ({
  fetchSystemOverview: jest.fn().mockRejectedValue(new Error('system error')),
  fetchServices: jest.fn().mockResolvedValue([]),
  fetchJobs: jest.fn().mockResolvedValue([]),
  fetchSpotifyOverview: jest.fn().mockResolvedValue({ playlists: 0, artists: 0, tracks: 0, lastSync: '' }),
  fetchSoulseekOverview: jest.fn().mockResolvedValue({ downloads: 0, uploads: 0, queue: 0, lastSync: '' }),
  fetchMatchingStats: jest.fn().mockResolvedValue({ pending: 0, processed: 0, conflicts: 0, lastRun: '' })
}));

describe('Dashboard', () => {
  it('shows toast on fetch error', async () => {
    renderWithProviders(<Dashboard />, { toastFn: toastMock });
    await waitFor(() => expect(toastMock).toHaveBeenCalled());
  });
});
