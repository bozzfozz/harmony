import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import ArtistsPage from '../pages/ArtistsPage';
import { renderWithProviders } from '../test-utils';
import {
  fetchArtistPreferences,
  fetchArtistReleases,
  fetchFollowedArtists,
  saveArtistPreferences,
  ArtistPreferenceEntry,
  SpotifyArtist,
  SpotifyArtistRelease
} from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  fetchFollowedArtists: jest.fn(),
  fetchArtistReleases: jest.fn(),
  fetchArtistPreferences: jest.fn(),
  saveArtistPreferences: jest.fn()
}));

const mockedFetchFollowed = fetchFollowedArtists as jest.MockedFunction<typeof fetchFollowedArtists>;
const mockedFetchReleases = fetchArtistReleases as jest.MockedFunction<typeof fetchArtistReleases>;
const mockedFetchPreferences = fetchArtistPreferences as jest.MockedFunction<typeof fetchArtistPreferences>;
const mockedSavePreferences = saveArtistPreferences as jest.MockedFunction<typeof saveArtistPreferences>;

const createArtist = (overrides: Partial<SpotifyArtist> = {}): SpotifyArtist => ({
  id: overrides.id ?? 'artist-1',
  name: overrides.name ?? 'Artist One',
  images: overrides.images ?? [],
  followers: overrides.followers
});

const createRelease = (overrides: Partial<SpotifyArtistRelease> = {}): SpotifyArtistRelease => ({
  id: overrides.id ?? 'release-1',
  name: overrides.name ?? 'Release One',
  album_type: overrides.album_type ?? 'album',
  release_date: overrides.release_date ?? '2023-04-20',
  total_tracks: overrides.total_tracks ?? 12
});

const createPreference = (overrides: Partial<ArtistPreferenceEntry> = {}): ArtistPreferenceEntry => ({
  artist_id: overrides.artist_id ?? 'artist-1',
  release_id: overrides.release_id ?? 'release-1',
  selected: overrides.selected ?? false
});

describe('ArtistsPage', () => {
  const toastMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockedFetchPreferences.mockResolvedValue([]);
    mockedFetchReleases.mockResolvedValue([]);
    mockedSavePreferences.mockResolvedValue([]);
  });

  it('lädt gefolgte Artists', async () => {
    mockedFetchFollowed.mockResolvedValue([createArtist({ name: 'Daft Punk' })]);

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    expect(await screen.findByText('Daft Punk')).toBeInTheDocument();
    expect(screen.getByText('Releases unbekannt')).toBeInTheDocument();
  });

  it('zeigt Releases eines ausgewählten Artists an', async () => {
    mockedFetchFollowed.mockResolvedValue([
      createArtist({ id: 'artist-1', name: 'Daft Punk' }),
      createArtist({ id: 'artist-2', name: 'Justice' })
    ]);
    mockedFetchPreferences.mockResolvedValue([createPreference({ artist_id: 'artist-1', selected: true })]);
    mockedFetchReleases.mockImplementation(async (artistId) => {
      if (artistId === 'artist-1') {
        return [createRelease({ name: 'Discovery', album_type: 'album', release_date: '2001-03-12', total_tracks: 14 })];
      }
      return [];
    });

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    await userEvent.click(await screen.findByText('Daft Punk'));

    await waitFor(() => expect(mockedFetchReleases).toHaveBeenCalledWith('artist-1'));

    expect(await screen.findByText('Discovery')).toBeInTheDocument();
    expect(screen.getByText('Album')).toBeInTheDocument();
    expect(screen.getByText('2001')).toBeInTheDocument();
    expect(screen.getByText('14')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /Discovery/ })).toBeChecked();
  });

  it('erlaubt das Ändern und Speichern der Auswahl', async () => {
    mockedFetchFollowed.mockResolvedValue([createArtist({ id: 'artist-1', name: 'Hot Chip' })]);
    mockedFetchPreferences.mockResolvedValue([
      createPreference({ artist_id: 'artist-1', release_id: 'release-1', selected: false }),
      createPreference({ artist_id: 'artist-1', release_id: 'release-2', selected: false })
    ]);
    mockedFetchReleases.mockResolvedValue([
      createRelease({ id: 'release-1', name: 'The Warning', album_type: 'album', release_date: '2006-05-22' }),
      createRelease({ id: 'release-2', name: 'Over and Over', album_type: 'single', release_date: '2005-10-31' })
    ]);
    mockedSavePreferences.mockResolvedValue([
      createPreference({ artist_id: 'artist-1', release_id: 'release-1', selected: true }),
      createPreference({ artist_id: 'artist-1', release_id: 'release-2', selected: false })
    ]);

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    await userEvent.click(await screen.findByText('Hot Chip'));

    const switches = await screen.findAllByRole('switch');
    expect(switches).toHaveLength(2);

    await userEvent.click(switches[0]);

    const saveButton = screen.getByRole('button', { name: 'Änderungen speichern' });
    expect(saveButton).toBeEnabled();

    await userEvent.click(saveButton);

    await waitFor(() =>
      expect(mockedSavePreferences).toHaveBeenCalledWith([
        { artist_id: 'artist-1', release_id: 'release-1', selected: true },
        { artist_id: 'artist-1', release_id: 'release-2', selected: false }
      ])
    );
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Präferenzen gespeichert' })
    );
  });

  it('zeigt einen Fehler-Toast, wenn Artists nicht geladen werden können', async () => {
    mockedFetchFollowed.mockRejectedValue(new Error('network error'));

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Artists konnten nicht geladen werden' })
      )
    );
  });
});
