import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';

import LibraryPage from '../pages/Library';
import { renderWithProviders } from '../test-utils';
import {
  getArtistPreferences,
  getArtistReleases,
  getFollowedArtists,
  saveArtistPreferences
} from '../api/services/spotify';
import { getDownloads } from '../api/services/downloads';
import { addWatchlistArtist, getWatchlist, removeWatchlistArtist } from '../api/services/search';

jest.mock('../api/services/spotify', () => ({
  ...jest.requireActual('../api/services/spotify'),
  getFollowedArtists: jest.fn(),
  getArtistPreferences: jest.fn(),
  getArtistReleases: jest.fn(),
  saveArtistPreferences: jest.fn()
}));

jest.mock('../api/services/downloads', () => ({
  ...jest.requireActual('../api/services/downloads'),
  getDownloads: jest.fn()
}));

jest.mock('../api/services/search', () => ({
  ...jest.requireActual('../api/services/search'),
  getWatchlist: jest.fn(),
  addWatchlistArtist: jest.fn(),
  removeWatchlistArtist: jest.fn()
}));

const mockedGetFollowedArtists = getFollowedArtists as jest.MockedFunction<typeof getFollowedArtists>;
const mockedGetArtistPreferences = getArtistPreferences as jest.MockedFunction<typeof getArtistPreferences>;
const mockedGetArtistReleases = getArtistReleases as jest.MockedFunction<typeof getArtistReleases>;
const mockedSaveArtistPreferences = saveArtistPreferences as jest.MockedFunction<typeof saveArtistPreferences>;
const mockedGetDownloads = getDownloads as jest.MockedFunction<typeof getDownloads>;
const mockedGetWatchlist = getWatchlist as jest.MockedFunction<typeof getWatchlist>;
const mockedAddWatchlist = addWatchlistArtist as jest.MockedFunction<typeof addWatchlistArtist>;
const mockedRemoveWatchlist = removeWatchlistArtist as jest.MockedFunction<typeof removeWatchlistArtist>;

describe('LibraryPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetFollowedArtists.mockResolvedValue([]);
    mockedGetArtistPreferences.mockResolvedValue([]);
    mockedGetArtistReleases.mockResolvedValue([]);
    mockedSaveArtistPreferences.mockResolvedValue([]);
    mockedGetDownloads.mockResolvedValue([]);
    mockedGetWatchlist.mockResolvedValue([]);
    mockedAddWatchlist.mockResolvedValue({
      id: 1,
      spotify_artist_id: 'artist',
      name: 'Artist',
      created_at: new Date().toISOString(),
      last_checked: null
    } as never);
    mockedRemoveWatchlist.mockResolvedValue();
  });

  it('zeigt standardmäßig den Artists-Tab und setzt den Query-Parameter', async () => {
    renderWithProviders(<LibraryPage />, { route: '/library' });

    await waitFor(() => expect(window.location.search).toContain('tab=artists'));
    expect(screen.getByText('Gefolgte Artists')).toBeInTheDocument();
    expect(mockedGetFollowedArtists).toHaveBeenCalled();
  });

  it('wechselt zum Downloads-Tab bei Klick und rendert die entsprechende Ansicht', async () => {
    renderWithProviders(<LibraryPage />, { route: '/library?tab=artists' });

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Artists' })).toHaveAttribute('data-state', 'active'));

    await userEvent.click(screen.getByRole('tab', { name: 'Downloads' }));

    await waitFor(() => expect(window.location.search).toContain('tab=downloads'));
    expect(await screen.findByText('Download-Management')).toBeInTheDocument();
    expect(mockedGetDownloads).toHaveBeenCalled();
  });

  it('öffnet den Watchlist-Tab bei direkter Navigation', async () => {
    renderWithProviders(<LibraryPage />, { route: '/library?tab=watchlist' });

    await waitFor(() => expect(window.location.search).toContain('tab=watchlist'));
    expect(await screen.findByLabelText('Spotify-Artist-ID')).toBeInTheDocument();
    expect(mockedGetWatchlist).toHaveBeenCalled();
  });
});
