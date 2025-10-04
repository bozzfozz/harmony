import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SettingsPage from '../pages/SettingsPage';
import { renderWithProviders } from '../test-utils';
import { getSettings, updateSettings, testServiceConnection } from '../api/services/system';
import { getSpotifyStatus } from '../api/services/spotify';

type GetSettingsMock = jest.MockedFunction<typeof getSettings>;
type UpdateSettingsMock = jest.MockedFunction<typeof updateSettings>;
type TestServiceConnectionMock = jest.MockedFunction<typeof testServiceConnection>;
type GetSpotifyStatusMock = jest.MockedFunction<typeof getSpotifyStatus>;

jest.mock('../api/services/system', () => ({
  ...jest.requireActual('../api/services/system'),
  getSettings: jest.fn(),
  updateSettings: jest.fn(),
  testServiceConnection: jest.fn()
}));

jest.mock('../api/services/spotify', () => ({
  ...jest.requireActual('../api/services/spotify'),
  getSpotifyStatus: jest.fn()
}));

const mockedGetSettings = getSettings as GetSettingsMock;
const mockedUpdateSettings = updateSettings as UpdateSettingsMock;
const mockedTestServiceConnection = testServiceConnection as TestServiceConnectionMock;
const mockedGetSpotifyStatus = getSpotifyStatus as GetSpotifyStatusMock;

const toastMock = jest.fn();

describe('SettingsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetSettings.mockResolvedValue({
      settings: {
        SPOTIFY_CLIENT_ID: 'abc',
        SPOTIFY_CLIENT_SECRET: 'secret',
        SPOTIFY_REDIRECT_URI: 'https://example.com/callback'
      }
    });
    mockedUpdateSettings.mockResolvedValue();
    mockedGetSpotifyStatus.mockResolvedValue({
      status: 'unconfigured',
      free_available: true,
      pro_available: false,
      authenticated: false
    });
  });

  it('lädt und speichert Einstellungen', async () => {
    renderWithProviders(<SettingsPage />, { toastFn: toastMock, route: '/settings' });

    const input = await screen.findByLabelText('Client ID');
    expect(input).toHaveValue('abc');

    await userEvent.clear(input);
    await userEvent.type(input, 'updated-id');

    const saveButton = screen.getByRole('button', { name: 'Save changes' });
    await userEvent.click(saveButton);

    await waitFor(() =>
      expect(mockedUpdateSettings).toHaveBeenCalledWith([
        { key: 'SPOTIFY_CLIENT_ID', value: 'updated-id' }
      ])
    );
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Spotify settings saved' }));
  });

  it('prüft Dienst-Verbindung und zeigt Ergebnis an', async () => {
    mockedTestServiceConnection.mockResolvedValue({
      service: 'spotify',
      status: 'ok',
      missing: [],
      optional_missing: []
    });

    renderWithProviders(<SettingsPage />, { toastFn: toastMock, route: '/settings' });

    const testButton = await screen.findByRole('button', { name: 'Verbindung testen' });
    await userEvent.click(testButton);

    await waitFor(() => expect(mockedTestServiceConnection).toHaveBeenCalledWith('spotify'));
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: '✅ Spotify-Verbindung erfolgreich' })
    );
  });
});
