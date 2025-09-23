import userEvent from '@testing-library/user-event';
import { rest } from 'msw';
import { screen } from '@testing-library/react';
import SoulseekPage from '../src/pages/SoulseekPage';
import { renderWithProviders } from '../src/test-utils';
import { server } from './server';

describe('SoulseekPage', () => {
  it('shows downloads, performs search and saves settings', async () => {
    renderWithProviders(<SoulseekPage />);

    await screen.findByText(/Status & Warteschlange/i);
    expect(screen.getByText(/Artist - Song.mp3/)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText(/Dateien oder Nutzer/i), 'Demo');
    await userEvent.click(screen.getByRole('button', { name: /Suchen/i }));
    await screen.findByText(/Demo.mp3/);

    await userEvent.click(screen.getByRole('tab', { name: /Einstellungen/i }));
    const urlField = await screen.findByLabelText(/slskd URL/i);
    await userEvent.clear(urlField);
    await userEvent.type(urlField, 'http://slskd.example');

    const saveButton = screen.getByRole('button', { name: /Speichern/i });
    await userEvent.click(saveButton);
    expect(saveButton).toBeDisabled();
    await screen.findByText('✅ Einstellungen gespeichert');
  });

  it('shows toast when downloads fail', async () => {
    server.use(rest.get('http://localhost/soulseek/downloads', (_req, res, ctx) => res(ctx.status(500))));

    renderWithProviders(<SoulseekPage />);
    await screen.findByText('❌ Fehler beim Laden');
  });
});
