import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import ArtistsPage from '../pages/ArtistsPage';
import { renderWithProviders } from '../test-utils';
import {
  getArtistPreferences,
  getArtistReleases,
  getFollowedArtists,
  saveArtistPreferences,
  ArtistPreferenceEntry,
  SpotifyArtist,
  SpotifyArtistRelease
} from '../lib/api';

jest.mock('../lib/api', () => ({
  ...jest.requireActual('../lib/api'),
  getFollowedArtists: jest.fn(),
  getArtistReleases: jest.fn(),
  getArtistPreferences: jest.fn(),
  saveArtistPreferences: jest.fn()
}));

const mockedGetFollowed = getFollowedArtists as jest.MockedFunction<typeof getFollowedArtists>;
const mockedGetReleases = getArtistReleases as jest.MockedFunction<typeof getArtistReleases>;
const mockedGetPreferences = getArtistPreferences as jest.MockedFunction<typeof getArtistPreferences>;
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
    mockedGetPreferences.mockResolvedValue([]);
    mockedGetReleases.mockResolvedValue([]);
    mockedSavePreferences.mockResolvedValue([]);
  });

  it('lädt gefolgte Artists', async () => {
    mockedGetFollowed.mockResolvedValue([createArtist({ name: 'Daft Punk' })]);

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    expect(await screen.findByText('Daft Punk')).toBeInTheDocument();
    expect(screen.getByText('Releases unbekannt')).toBeInTheDocument();
  });

  it('zeigt Releases eines ausgewählten Artists an', async () => {
    mockedGetFollowed.mockResolvedValue([
      createArtist({ id: 'artist-1', name: 'Daft Punk' }),
      createArtist({ id: 'artist-2', name: 'Justice' })
    ]);
    mockedGetPreferences.mockResolvedValue([createPreference({ artist_id: 'artist-1', selected: true })]);
    mockedGetReleases.mockImplementation(async (artistId) => {
      if (artistId === 'artist-1') {
        return [createRelease({ name: 'Discovery', album_type: 'album', release_date: '2001-03-12', total_tracks: 14 })];
      }
      return [];
    });

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    await userEvent.click(await screen.findByText('Daft Punk'));

    await waitFor(() => expect(mockedGetReleases).toHaveBeenCalledWith('artist-1'));

    expect(await screen.findByText('Discovery')).toBeInTheDocument();
    expect(screen.getByText('Album')).toBeInTheDocument();
    expect(screen.getByText('2001')).toBeInTheDocument();
    expect(screen.getByText('14')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /Discovery/ })).toBeChecked();
  });

  it('erlaubt das Ändern und Speichern der Auswahl', async () => {
    mockedGetFollowed.mockResolvedValue([createArtist({ id: 'artist-1', name: 'Hot Chip' })]);
    mockedGetPreferences.mockResolvedValue([
      createPreference({ artist_id: 'artist-1', release_id: 'release-1', selected: false }),
      createPreference({ artist_id: 'artist-1', release_id: 'release-2', selected: false })
    ]);
    mockedGetReleases.mockResolvedValue([
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
    mockedGetFollowed.mockRejectedValue(new Error('network error'));

    renderWithProviders(<ArtistsPage />, { toastFn: toastMock, route: '/artists' });

    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Artists konnten nicht geladen werden' })
      )
    );
  });
});
