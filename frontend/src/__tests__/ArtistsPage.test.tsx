import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';

import ArtistsPage from '../pages/Artists/ArtistsPage';
import { renderWithProviders } from '../test-utils';
import {
  addArtistToWatchlist,
  listArtists,
  removeWatchlistEntry,
  updateWatchlistEntry
} from '../api/services/artists';

jest.mock('../api/services/artists', () => ({
  ...jest.requireActual('../api/services/artists'),
  listArtists: jest.fn(),
  addArtistToWatchlist: jest.fn(),
  updateWatchlistEntry: jest.fn(),
  removeWatchlistEntry: jest.fn()
}));

const mockedListArtists = listArtists as jest.MockedFunction<typeof listArtists>;
const mockedAddArtist = addArtistToWatchlist as jest.MockedFunction<typeof addArtistToWatchlist>;
const mockedUpdateWatchlist = updateWatchlistEntry as jest.MockedFunction<typeof updateWatchlistEntry>;
const mockedRemoveWatchlist = removeWatchlistEntry as jest.MockedFunction<typeof removeWatchlistEntry>;

const createListResponse = () => ({
  items: [
    {
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
      matches_pending: 2,
      releases_total: 5,
      updated_at: '2024-05-02T10:00:00Z'
    }
  ],
  total: 1,
  page: 1,
  per_page: 25
});

describe('ArtistsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedListArtists.mockResolvedValue(createListResponse());
    mockedAddArtist.mockResolvedValue(createListResponse().items[0] ?? null);
    mockedUpdateWatchlist.mockResolvedValue({
      id: 'watch-1',
      enabled: true,
      priority: 'high',
      interval_days: 7,
      last_synced_at: '2024-05-01T10:00:00Z',
      next_sync_at: '2024-05-08T10:00:00Z'
    });
    mockedRemoveWatchlist.mockResolvedValue();
  });

  it('lädt und zeigt die Watchlist', async () => {
    renderWithProviders(<ArtistsPage />, { route: '/artists' });

    expect(await screen.findByRole('heading', { name: 'Artist Watchlist' })).toBeInTheDocument();
    await waitFor(() => expect(mockedListArtists).toHaveBeenCalled());
    expect(await screen.findByText('First Artist')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Details' })).toBeInTheDocument();
  });

  it('passt Priorität, Intervall und Filter an und entfernt Artists', async () => {
    const toastSpy = jest.fn();
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<ArtistsPage />, { route: '/artists', toastFn: toastSpy });

    await screen.findByText('First Artist');

    await userEvent.click(screen.getByRole('combobox', { name: 'Priorität für First Artist' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Hoch' }));

    await waitFor(() =>
      expect(mockedUpdateWatchlist).toHaveBeenCalledWith('watch-1', { priority: 'high' })
    );

    await userEvent.click(screen.getByRole('combobox', { name: 'Sync-Intervall für First Artist' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Alle 14 Tage' }));

    await waitFor(() =>
      expect(mockedUpdateWatchlist).toHaveBeenCalledWith('watch-1', { interval_days: 14 })
    );

    await userEvent.click(screen.getByRole('combobox', { name: 'Gesundheitsstatus filtern' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Warnung' }));

    await waitFor(() => {
      const lastCall = mockedListArtists.mock.calls[mockedListArtists.mock.calls.length - 1]?.[0];
      expect(lastCall).toMatchObject({ health: 'warning', watchlistOnly: true });
    });

    await userEvent.click(screen.getByRole('button', { name: 'Entfernen' }));

    await waitFor(() => expect(mockedRemoveWatchlist).toHaveBeenCalledWith('watch-1'));
    expect(confirmSpy).toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  it('fügt einen Artist über das Formular hinzu', async () => {
    renderWithProviders(<ArtistsPage />, { route: '/artists' });

    await screen.findByText('First Artist');

    await userEvent.type(screen.getByLabelText('Name'), 'Neuer Artist');
    await userEvent.type(screen.getByLabelText('Spotify-Artist-ID'), 'new-artist');
    await userEvent.click(screen.getByRole('button', { name: /Zur Watchlist hinzufügen/i }));

    await waitFor(() =>
      expect(mockedAddArtist).toHaveBeenCalledWith({ name: 'Neuer Artist', spotify_artist_id: 'new-artist' })
    );
  });
});
