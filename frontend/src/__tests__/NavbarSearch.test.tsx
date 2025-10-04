import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import Navbar from '../../layout/Navbar';
import { ThemeProvider } from '../components/theme-provider';
import type { SpotifySearchResults } from '../../layout/../src/api/services/spotify';
import { searchSpotify } from '../../layout/../src/api/services/spotify';

jest.mock('../../layout/../src/api/services/spotify', () => ({
  searchSpotify: jest.fn()
}));

const mockedSearchSpotify = searchSpotify as jest.MockedFunction<typeof searchSpotify>;

const renderNavbar = () =>
  render(
    <MemoryRouter>
      <ThemeProvider>
        <Navbar />
      </ThemeProvider>
    </MemoryRouter>
  );

beforeEach(() => {
  mockedSearchSpotify.mockReset();
});

describe('Navbar search', () => {
  it('submits a query and displays grouped results', async () => {
    const mockResults: SpotifySearchResults = {
      tracks: [
        {
          type: 'track',
          id: 'track-1',
          name: 'Hysteria',
          artists: ['Muse'],
          album: 'Absolution',
          durationMs: 214000
        }
      ],
      artists: [
        {
          type: 'artist',
          id: 'artist-1',
          name: 'Muse',
          imageUrl: null,
          followers: 1532000,
          genres: ['Alternative Rock', 'Space Rock']
        }
      ],
      albums: [
        {
          type: 'album',
          id: 'album-1',
          name: 'Black Holes & Revelations',
          imageUrl: null,
          releaseDate: '2006-07-03',
          artists: ['Muse']
        }
      ]
    };
    mockedSearchSpotify.mockResolvedValue(mockResults);

    const user = userEvent.setup();
    renderNavbar();

    const input = screen.getByRole('searchbox', { name: /search/i });
    await act(async () => {
      await user.type(input, 'Muse');
      await user.keyboard('{Enter}');
    });

    expect(mockedSearchSpotify).toHaveBeenCalledWith('Muse');
    expect(await screen.findByRole('heading', { name: /tracks/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /hysteria/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /black holes & revelations/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /^muse/i })).toBeInTheDocument();
  });

  it('does not call the API when the query is empty', async () => {
    const user = userEvent.setup();
    renderNavbar();

    const input = screen.getByRole('searchbox', { name: /search/i });
    await act(async () => {
      await user.click(input);
      await user.keyboard('{Enter}');
    });

    expect(mockedSearchSpotify).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(/please enter a search term/i);
  });
});
