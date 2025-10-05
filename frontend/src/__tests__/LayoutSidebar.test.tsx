import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Layout from '../components/Layout';
import { renderWithProviders } from '../test-utils';
import { useIntegrationHealth } from '../hooks/useIntegrationHealth';

jest.mock('../hooks/useIntegrationHealth', () => ({
  useIntegrationHealth: jest.fn()
}));

const mockedUseIntegrationHealth = useIntegrationHealth as jest.MockedFunction<typeof useIntegrationHealth>;

describe('Layout sidebar interactions', () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedUseIntegrationHealth.mockReturnValue({
      services: {
        soulseek: {
          online: true,
          degraded: false,
          misconfigured: false,
          status: 'ok'
        },
        matching: {
          online: true,
          degraded: false,
          misconfigured: false,
          status: 'ok'
        }
      },
      isLoading: false,
      errors: {},
      refresh: jest.fn()
    });
  });

  it('collapses navigation labels but keeps icons and tooltips accessible', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/dashboard' }
    );

    const collapseButton = screen.getByRole('button', { name: /sidebar einklappen/i });
    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' });
    const dashboardLabel = within(dashboardLink).getByText('Dashboard');
    const contentWrapper = screen.getByTestId('content-wrapper');

    expect(dashboardLabel).not.toHaveClass('sr-only');
    expect(contentWrapper).toHaveClass('lg:ml-64');

    await user.click(collapseButton);

    expect(dashboardLabel).toHaveClass('sr-only');

    const dashboardIcon = within(dashboardLink).getByTestId('nav-icon-dashboard');
    expect(dashboardIcon).toBeVisible();
    expect(dashboardLink).toHaveAttribute('aria-label', 'Dashboard');

    const tooltip = screen.getByTestId('nav-tooltip-dashboard');
    expect(tooltip).toHaveTextContent('Dashboard');

    expect(contentWrapper).toHaveClass('lg:ml-20');
  });

  it('renders warning badges for degraded services', async () => {
    mockedUseIntegrationHealth.mockReturnValue({
      services: {
        soulseek: {
          online: false,
          degraded: true,
          misconfigured: false,
          status: 'down'
        },
        matching: {
          online: true,
          degraded: true,
          misconfigured: false,
          status: 'degraded'
        }
      },
      isLoading: false,
      errors: {},
      refresh: jest.fn()
    });

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/matching' }
    );

    const matchingLink = screen.getByRole('link', { name: /Matching – Warnung/i });
    expect(matchingLink).toBeInTheDocument();
    expect(within(matchingLink).getByText('Eingeschränkt')).toBeInTheDocument();

    const soulseekLink = screen.getByRole('link', { name: /Soulseek – Warnung/i });
    expect(soulseekLink).toBeInTheDocument();
    expect(within(soulseekLink).getByText('Offline')).toBeInTheDocument();

    const matchingTooltip = screen.getByTestId('nav-tooltip-matching');
    expect(within(matchingTooltip).getByText(/Warnung: Dienst eingeschränkt/)).toBeInTheDocument();
  });

  it('keeps warning indicators accessible when the sidebar is collapsed', async () => {
    mockedUseIntegrationHealth.mockReturnValue({
      services: {
        soulseek: {
          online: true,
          degraded: true,
          misconfigured: true,
          status: 'error'
        },
        matching: {
          online: true,
          degraded: false,
          misconfigured: false,
          status: 'ok'
        }
      },
      isLoading: false,
      errors: {},
      refresh: jest.fn()
    });

    const user = userEvent.setup();

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/soulseek' }
    );

    const collapseButton = screen.getByRole('button', { name: /sidebar einklappen/i });
    await user.click(collapseButton);

    const soulseekLink = screen.getByRole('link', { name: /Soulseek – Warnung/i });
    const tooltip = screen.getByTestId('nav-tooltip-soulseek');
    expect(within(tooltip).getByText(/Warnung: Konfiguration prüfen/)).toBeInTheDocument();
    const indicator = within(soulseekLink).getByText('Fehler');
    expect(indicator).toHaveClass('sr-only');
  });

  it('shows offline indicators when integration health queries fail', () => {
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});

    mockedUseIntegrationHealth.mockReturnValue({
      services: {
        soulseek: {
          online: false,
          degraded: true,
          misconfigured: false,
          status: 'unknown'
        },
        matching: {
          online: false,
          degraded: true,
          misconfigured: false,
          status: 'unknown'
        }
      },
      isLoading: false,
      errors: { system: new Error('unreachable') },
      refresh: jest.fn()
    });

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/dashboard' }
    );

    const soulseekLink = screen.getByRole('link', { name: /Soulseek – Warnung: Dienst offline/i });
    expect(within(soulseekLink).getByText('Offline')).toBeInTheDocument();

    const matchingLink = screen.getByRole('link', { name: /Matching – Warnung: Dienst offline/i });
    expect(within(matchingLink).getByText('Offline')).toBeInTheDocument();

    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it('restores the collapsed state from localStorage and persists user changes', async () => {
    window.localStorage.setItem('layout:sidebarCollapsed', JSON.stringify(true));

    const user = userEvent.setup();

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/dashboard' }
    );

    const collapseToggle = screen.getByRole('button', { name: /sidebar erweitern/i });
    const aside = screen.getByRole('complementary');
    const contentWrapper = screen.getByTestId('content-wrapper');

    expect(aside).toHaveAttribute('data-collapsed', 'true');
    expect(contentWrapper).toHaveClass('lg:ml-20');

    await user.click(collapseToggle);

    expect(aside).toHaveAttribute('data-collapsed', 'false');
    expect(window.localStorage.getItem('layout:sidebarCollapsed')).toBe(JSON.stringify(false));
  });

  it('keeps mobile navigation toggling functional when collapsed state is persisted', async () => {
    window.localStorage.setItem('layout:sidebarCollapsed', JSON.stringify(true));

    const user = userEvent.setup();

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/dashboard' }
    );

    const aside = screen.getByRole('complementary');
    const mobileToggle = screen.getByRole('button', { name: /navigation umschalten/i });

    expect(aside).toHaveAttribute('data-collapsed', 'true');
    expect(aside.className).toContain('-translate-x-full');

    await user.click(mobileToggle);

    expect(aside.className).toContain('translate-x-0');
    expect(aside).toHaveAttribute('data-collapsed', 'true');
  });

  it('falls back gracefully when storage access fails', async () => {
    const originalLocalStorage = window.localStorage;
    const failingStorage = {
      getItem: jest.fn(() => {
        throw new Error('blocked');
      }),
      setItem: jest.fn(() => {
        throw new Error('blocked');
      }),
      removeItem: jest.fn(() => {
        throw new Error('blocked');
      })
    } as unknown as Storage;

    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: failingStorage
    });

    const user = userEvent.setup();

    renderWithProviders(
      <Layout>
        <div>Test content</div>
      </Layout>,
      { route: '/dashboard' }
    );

    const collapseButton = screen.getByRole('button', { name: /sidebar einklappen/i });

    await expect(user.click(collapseButton)).resolves.toBeUndefined();

    const dashboardLink = screen.getByRole('link', { name: 'Dashboard' });
    const dashboardLabel = within(dashboardLink).getByText('Dashboard');
    expect(dashboardLabel).toHaveClass('sr-only');

    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: originalLocalStorage
    });
  });
});
