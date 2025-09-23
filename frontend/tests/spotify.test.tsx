import { screen, userEvent } from '../src/testing/dom-testing';
import SpotifyPage from '../src/pages/SpotifyPage';
import { renderWithProviders } from '../src/test-utils';
import { rest, server } from './server';

describe('SpotifyPage', () => {
  it('shows playlists, performs search and saves settings', async () => {
    renderWithProviders(<SpotifyPage />);

    await screen.findByText(/Spotify Playlists/i);
    expect(screen.getByText(/Daily Mix/)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText(/Track oder Artist/i), 'Test');
    await userEvent.click(screen.getByRole('button', { name: /Suchen/i }));
    await screen.findByText(/Track Test/);

    await userEvent.click(screen.getByRole('tab', { name: /Einstellungen/i }));
    const clientIdField = await screen.findByLabelText(/Client ID/i);
    await userEvent.clear(clientIdField);
    await userEvent.type(clientIdField, 'updated-client');

    const saveButton = screen.getByRole('button', { name: /Speichern/i });
    await userEvent.click(saveButton);
    expect(saveButton).toBeDisabled();
    await screen.findByText('✅ Einstellungen gespeichert');
  });

  it('shows toast when playlist loading fails', async () => {
    server.use(
      rest.get('http://localhost/spotify/playlists', () => ({ status: 500 }))
    );

    renderWithProviders(<SpotifyPage />);
    await screen.findByText('❌ Fehler beim Laden');
  });
});
