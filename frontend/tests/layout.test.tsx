import { screen, waitFor, userEvent } from '../src/testing/dom-testing';
import App from '../src/App';
import { renderWithProviders } from '../src/test-utils';

describe('Layout navigation', () => {
  it('renders navigation and switches pages', async () => {
    renderWithProviders(<App />, { routerEntries: ['/dashboard'] });

    await screen.findByText(/System Information/i);

    expect(screen.getByRole('link', { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Spotify/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Plex/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Soulseek/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('link', { name: /Spotify/i }));
    await screen.findByText(/Spotify Playlists/i);
  });

  it('toggles dark and light mode', async () => {
    renderWithProviders(<App />, { routerEntries: ['/dashboard'] });

    const themeSwitch = await screen.findByRole('switch', { name: /toggle theme/i });
    expect(document.documentElement.classList.contains('dark')).toBe(false);

    await userEvent.click(themeSwitch);

    await waitFor(() => expect(document.documentElement.classList.contains('dark')).toBe(true));
  });
});
