import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SpotifyPage from '../pages/SpotifyPage';
import { renderWithProviders } from '../test-utils';
import {
  getSpotifyStatus,
  startSpotifyProOAuth,
  getSpotifyProOAuthStatus,
  refreshSpotifyProSession
} from '../api/services/spotify';

jest.mock('../api/services/spotify', () => ({
  ...jest.requireActual('../api/services/spotify'),
  getSpotifyStatus: jest.fn(),
  startSpotifyProOAuth: jest.fn(),
  getSpotifyProOAuthStatus: jest.fn(),
  refreshSpotifyProSession: jest.fn()
}));

type GetSpotifyStatusMock = jest.MockedFunction<typeof getSpotifyStatus>;
type StartSpotifyProOAuthMock = jest.MockedFunction<typeof startSpotifyProOAuth>;
type GetSpotifyProOAuthStatusMock = jest.MockedFunction<typeof getSpotifyProOAuthStatus>;
type RefreshSpotifyProSessionMock = jest.MockedFunction<typeof refreshSpotifyProSession>;

const mockedGetSpotifyStatus = getSpotifyStatus as GetSpotifyStatusMock;
const mockedStartSpotifyProOAuth = startSpotifyProOAuth as StartSpotifyProOAuthMock;
const mockedGetSpotifyProOAuthStatus = getSpotifyProOAuthStatus as GetSpotifyProOAuthStatusMock;
const mockedRefreshSpotifyProSession = refreshSpotifyProSession as RefreshSpotifyProSessionMock;

const toastMock = jest.fn();

describe('SpotifyPage OAuth Flow', () => {
  let openSpy: jest.SpyInstance<Window | null, Parameters<typeof window.open>>;
  let popupMock: { closed: boolean; close: jest.Mock; focus: jest.Mock };

  beforeEach(() => {
    jest.clearAllMocks();
    sessionStorage.clear();
    popupMock = {
      closed: false,
      close: jest.fn(() => {
        popupMock.closed = true;
      }),
      focus: jest.fn()
    };
    openSpy = jest.spyOn(window, 'open').mockImplementation(() => popupMock as unknown as Window);
    mockedGetSpotifyStatus.mockResolvedValue({
      status: 'unauthenticated',
      free_available: true,
      pro_available: true,
      authenticated: false
    });
  });

  afterEach(() => {
    openSpy.mockRestore();
  });

  it('startet den OAuth-Flow und zeigt den Erfolgsdialog', async () => {
    mockedStartSpotifyProOAuth.mockResolvedValue({
      authorization_url: 'https://accounts.spotify.com/authorize',
      state: 'oauth-state',
      expires_at: null
    });
    mockedGetSpotifyProOAuthStatus.mockResolvedValue({
      status: 'authorized',
      state: 'oauth-state',
      authenticated: true,
      error: undefined,
      completed_at: null,
      profile: { display_name: 'Harmony Ops' }
    });
    mockedRefreshSpotifyProSession.mockResolvedValue({
      status: 'connected',
      free_available: true,
      pro_available: true,
      authenticated: true
    });

    renderWithProviders(<SpotifyPage />, { route: '/spotify', toastFn: toastMock });

    await screen.findByText('Spotify Status');

    await userEvent.click(screen.getByRole('button', { name: /Watchlist öffnen/i }));

    await waitFor(() => expect(mockedStartSpotifyProOAuth).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockedGetSpotifyProOAuthStatus).toHaveBeenCalledWith('oauth-state'));

    const dialog = await screen.findByRole('dialog', { name: /Spotify PRO verbunden/i });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Watchlist öffnen' })).toBeInTheDocument();
    expect(screen.getByText('Aktive Session vorhanden.')).toBeInTheDocument();
    expect(mockedRefreshSpotifyProSession).toHaveBeenCalled();
    expect(popupMock.close).toHaveBeenCalled();
  });

  it('meldet Fehler während des OAuth-Flows', async () => {
    mockedStartSpotifyProOAuth.mockResolvedValue({
      authorization_url: 'https://accounts.spotify.com/authorize',
      state: 'oauth-state',
      expires_at: null
    });
    mockedGetSpotifyProOAuthStatus.mockResolvedValue({
      status: 'failed',
      state: 'oauth-state',
      authenticated: false,
      error: 'Fehler: Zugriff verweigert',
      completed_at: null,
      profile: null
    });

    renderWithProviders(<SpotifyPage />, { route: '/spotify', toastFn: toastMock });

    await screen.findByText('Spotify Status');

    await userEvent.click(screen.getByRole('button', { name: /Watchlist öffnen/i }));

    await waitFor(() => expect(mockedGetSpotifyProOAuthStatus).toHaveBeenCalledWith('oauth-state'));
    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Spotify OAuth fehlgeschlagen' })
      )
    );
    expect(screen.queryByRole('dialog', { name: /Spotify PRO verbunden/i })).not.toBeInTheDocument();
  });

  it('meldet einen abgebrochenen OAuth-Flow', async () => {
    mockedStartSpotifyProOAuth.mockResolvedValue({
      authorization_url: 'https://accounts.spotify.com/authorize',
      state: 'oauth-state',
      expires_at: null
    });
    mockedGetSpotifyProOAuthStatus.mockResolvedValue({
      status: 'cancelled',
      state: 'oauth-state',
      authenticated: false,
      error: undefined,
      completed_at: null,
      profile: null
    });

    renderWithProviders(<SpotifyPage />, { route: '/spotify', toastFn: toastMock });

    await screen.findByText('Spotify Status');

    await userEvent.click(screen.getByRole('button', { name: /Watchlist öffnen/i }));

    await waitFor(() => expect(mockedGetSpotifyProOAuthStatus).toHaveBeenCalledWith('oauth-state'));
    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Spotify OAuth abgebrochen' })
      )
    );
  });
});
