import userEvent from '@testing-library/user-event';
import { rest } from 'msw';
import { screen } from '@testing-library/react';
import PlexPage from '../src/pages/PlexPage';
import { renderWithProviders } from '../src/test-utils';
import { server } from './server';

describe('PlexPage', () => {
  it('shows status, sessions and saves settings', async () => {
    renderWithProviders(<PlexPage />);

    await screen.findByText(/Verbindung/i);
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
    expect(screen.getByText(/Artists/)).toBeInTheDocument();
    expect(screen.getByText(/Song Title/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /Einstellungen/i }));
    const baseUrlField = await screen.findByLabelText(/Basis-URL/i);
    await userEvent.clear(baseUrlField);
    await userEvent.type(baseUrlField, 'http://plex.example');

    const saveButton = screen.getByRole('button', { name: /Speichern/i });
    await userEvent.click(saveButton);
    expect(saveButton).toBeDisabled();
    await screen.findByText('✅ Einstellungen gespeichert');
  });

  it('shows error toast when plex status fails', async () => {
    server.use(rest.get('http://localhost/plex/status', (_req, res, ctx) => res(ctx.status(500))));

    renderWithProviders(<PlexPage />);
    await screen.findByText('❌ Fehler beim Laden');
  });
});
