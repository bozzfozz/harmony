import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import FreeLinksPage from '../pages/free/LinksPage';
import { renderWithProviders } from '../test-utils';
import { postFreePlaylistLinks } from '../lib/api/freeLinks';
import { ApiError } from '../api/client';

jest.mock('../lib/api/freeLinks', () => ({
  postFreePlaylistLinks: jest.fn()
}));

const mockedPostFreePlaylistLinks = postFreePlaylistLinks as jest.MockedFunction<typeof postFreePlaylistLinks>;

describe('FreeLinksPage', () => {
  const toastMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders form and allows submitting a single valid url', async () => {
    mockedPostFreePlaylistLinks.mockResolvedValue({
      accepted: [{ playlist_id: 'AAA', url: 'https://open.spotify.com/playlist/AAA' }],
      skipped: []
    });

    renderWithProviders(<FreeLinksPage />, { route: '/free/links', toastFn: toastMock });

    const textarea = screen.getByLabelText('Playlist-Links');
    await userEvent.type(textarea, 'https://open.spotify.com/playlist/AAA');

    const submitButton = screen.getByRole('button', { name: 'Speichern' });
    await userEvent.click(submitButton);

    await waitFor(() => {
      expect(mockedPostFreePlaylistLinks).toHaveBeenCalledWith({ url: 'https://open.spotify.com/playlist/AAA' });
    });

    expect(await screen.findByText('AAA')).toBeInTheDocument();
    expect(textarea).toHaveValue('https://open.spotify.com/playlist/AAA');
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Playlist-Links gespeichert' }));
  });

  it('rejects non-playlist urls client-side', async () => {
    renderWithProviders(<FreeLinksPage />, { route: '/free/links', toastFn: toastMock });

    const textarea = screen.getByLabelText('Playlist-Links');
    await userEvent.type(textarea, 'https://example.com/not-a-playlist');

    const submitButton = screen.getByRole('button', { name: 'Speichern' });
    await userEvent.click(submitButton);

    expect(mockedPostFreePlaylistLinks).not.toHaveBeenCalled();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('https://example.com/not-a-playlist');
    expect(toastMock).not.toHaveBeenCalled();
  });

  it('submits multiple urls and shows accepted/skipped', async () => {
    mockedPostFreePlaylistLinks.mockResolvedValue({
      accepted: [{ playlist_id: 'AAA', url: 'https://open.spotify.com/playlist/AAA' }],
      skipped: [{ url: 'spotify:playlist:BBB', reason: 'duplicate' }]
    });

    renderWithProviders(<FreeLinksPage />, { route: '/free/links', toastFn: toastMock });

    const textarea = screen.getByLabelText('Playlist-Links');
    await userEvent.type(
      textarea,
      'https://open.spotify.com/playlist/AAA\nhttps://open.spotify.com/playlist/AAA?si=xyz\nspotify:playlist:BBB'
    );

    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    await waitFor(() => {
      expect(mockedPostFreePlaylistLinks).toHaveBeenCalledWith({
        urls: ['https://open.spotify.com/playlist/AAA', 'spotify:playlist:BBB']
      });
    });

    expect(await screen.findByText('AAA')).toBeInTheDocument();
    expect(screen.getByText('Bereits vorhanden')).toBeInTheDocument();
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: 'Playlist-Links gespeichert' }));
  });

  it.each([
    { status: 429, message: 'Zu viele Versuche' },
    { status: 503, message: 'Der Dienst antwortet aktuell nicht' }
  ])('handles $status errors with a user friendly toast', async ({ status, message }) => {
    const apiError = new ApiError({ code: 'ERR', message: 'upstream', status });
    mockedPostFreePlaylistLinks.mockRejectedValue(apiError);

    renderWithProviders(<FreeLinksPage />, { route: '/free/links', toastFn: toastMock });

    const textarea = screen.getByLabelText('Playlist-Links');
    await userEvent.type(textarea, 'https://open.spotify.com/playlist/AAA');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    await waitFor(() => {
      expect(mockedPostFreePlaylistLinks).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Speichern fehlgeschlagen',
          description: expect.stringContaining(message)
        })
      );
    });

    expect(screen.queryByText('AAA')).not.toBeInTheDocument();
  });
});
