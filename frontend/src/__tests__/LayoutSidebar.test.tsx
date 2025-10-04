import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Layout from '../components/Layout';
import { renderWithProviders } from '../test-utils';

describe('Layout sidebar interactions', () => {
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

    await user.hover(dashboardLink);
    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip).toHaveTextContent('Dashboard');

    expect(contentWrapper).toHaveClass('lg:ml-20');
  });
});
