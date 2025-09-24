import { screen, userEvent, waitFor } from '../../src/testing/dom-testing';
import SettingsPage from '../../src/pages/SettingsPage';
import { renderWithProviders } from '../../src/test-utils';
import { rest, server } from '../server';

describe('SettingsPage credentials', () => {
  const toastMock = jest.fn();

  afterEach(() => {
    toastMock.mockReset();
    server.resetHandlers();
  });

  it('masks sensitive inputs and allows testing Spotify credentials', async () => {
    renderWithProviders(<SettingsPage />, { toastFn: toastMock });

    const secretInput = (await screen.findByLabelText('Client secret')) as HTMLInputElement;
    expect(secretInput.type).toBe('password');

    const tokenInput = screen.getByLabelText('Access token') as HTMLInputElement;
    expect(tokenInput.type).toBe('password');

    const apiKeyInput = screen.getByLabelText('API key') as HTMLInputElement;
    expect(apiKeyInput.type).toBe('password');

    const testButtons = screen.getAllByRole('button', { name: 'Verbindung testen' });
    await userEvent.click(testButtons[0]);

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('✅ Spotify-Verbindung erfolgreich') })
      );
    });
  });

  it('shows a descriptive toast when Spotify credentials are incomplete', async () => {
    server.use(
      rest.get('http://localhost:8000/api/health/spotify', () => ({
        json: {
          service: 'spotify',
          status: 'fail',
          missing: ['SPOTIFY_CLIENT_SECRET'],
          optional_missing: []
        }
      }))
    );

    renderWithProviders(<SettingsPage />, { toastFn: toastMock });

    const spotifyButton = (await screen.findAllByRole('button', { name: 'Verbindung testen' }))[0];
    await userEvent.click(spotifyButton);

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('❌ Spotify-Verbindung fehlgeschlagen') })
      );
    });
  });
});
