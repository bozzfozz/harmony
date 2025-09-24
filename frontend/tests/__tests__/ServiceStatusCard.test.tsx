import { screen } from '../../src/testing/dom-testing';
import ServiceStatusCard from '../../src/components/ServiceStatusCard';
import { renderWithProviders } from '../../src/test-utils';

describe('ServiceStatusCard', () => {
  it('shows the connection state for each service', () => {
    renderWithProviders(
      <ServiceStatusCard connections={{ spotify: 'ok', plex: 'fail', soulseek: 'ok' }} />
    );

    expect(screen.getByLabelText('Verbunden')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Verbunden').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText('Fehlgeschlagen')).toBeInTheDocument();
    expect(screen.getByText('Spotify')).toBeInTheDocument();
    expect(screen.getByText('Plex')).toBeInTheDocument();
    expect(screen.getByText('Soulseek')).toBeInTheDocument();
  });

  it('renders a loading hint when the status is pending', () => {
    renderWithProviders(<ServiceStatusCard isLoading connections={{}} />);

    expect(screen.getAllByText('Prüfe…').length).toBe(3);
  });
});
