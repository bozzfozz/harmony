import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import AppRoutes from '../routes';

describe('AppRoutes', () => {
  const renderWithRoute = (route: string) =>
    render(
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    );

  it('renders the Soulseek page without redirecting', () => {
    renderWithRoute('/soulseek');

    expect(
      screen.getByRole('heading', { name: /Soulseek/i, level: 1 })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Soulseek-Community, um neue Musikquellen zu entdecken/i)
    ).toBeInTheDocument();
  });

  it('renders the Matching page without redirecting', () => {
    renderWithRoute('/matching');

    expect(
      screen.getByRole('heading', { name: /Matching/i, level: 1 })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Abgleichsstatus, vorgeschlagene Zuordnungen/i)
    ).toBeInTheDocument();
  });
});
