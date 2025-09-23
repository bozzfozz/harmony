import { fireEvent, screen, waitFor } from '@testing-library/react';
import SpotifyPage from '../pages/SpotifyPage';
import { renderWithProviders } from '../test-utils';

jest.mock('../lib/api', () => ({
  fetchSettings: jest.fn().mockResolvedValue({
    spotify: {
      clientId: 'abc',
      clientSecret: 'xyz'
    },
    plex: {},
    soulseek: {},
    beets: {}
  }),
  fetchSpotifyOverview: jest.fn().mockResolvedValue({
    playlists: 10,
    artists: 4,
    tracks: 120,
    lastSync: '2024-02-01T12:00:00Z'
  }),
  updateSettings: jest.fn().mockResolvedValue(true)
}));

const { fetchSettings, fetchSpotifyOverview, updateSettings } = jest.requireMock('../lib/api');

describe('SpotifyPage', () => {
  it('switches between tabs', async () => {
    renderWithProviders(<SpotifyPage />);
    await waitFor(() => expect(fetchSpotifyOverview).toHaveBeenCalled());
    expect(screen.getByText('Playlists')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /settings/i }));
    await waitFor(() => expect(screen.getByLabelText('clientId')).toBeInTheDocument());
  });

  it('submits updated settings', async () => {
    renderWithProviders(<SpotifyPage />);
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('tab', { name: /settings/i }));
    const input = await screen.findByLabelText('clientId');
    fireEvent.change(input, { target: { value: 'updated' } });
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
  });
});
