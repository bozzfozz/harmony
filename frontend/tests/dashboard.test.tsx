import { screen, within } from '../src/testing/dom-testing';
import Dashboard from '../src/pages/Dashboard';
import { renderWithProviders } from '../src/test-utils';
import { rest, server } from './server';

describe('Dashboard', () => {
  it('renders system information and downloads', async () => {
    renderWithProviders(<Dashboard />);

    await screen.findByText(/System Information/i);
    expect(screen.getByText(/Verbunden/i)).toBeInTheDocument();
    expect(screen.getByText(/Spotify Überblick/i)).toBeInTheDocument();

    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row');
    expect(rows.length).toBeGreaterThan(1);
    expect(within(rows[1]).getByText(/Artist - Song\.mp3/i)).toBeInTheDocument();
  });

  it('shows an error toast when a request fails', async () => {
    server.use(
      rest.get('http://localhost/spotify/status', () => ({ status: 500 }))
    );

    renderWithProviders(<Dashboard />);

    await screen.findByText('❌ Fehler beim Laden');
  });
});
