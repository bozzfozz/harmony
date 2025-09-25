import { fireEvent, screen } from '@testing-library/react';
import Navbar from '../../layout/Navbar';
import Sidebar from '../../layout/Sidebar';
import Layout from '../../layout/Layout';
import { renderWithProviders } from '../test-utils';

describe('Harmony layout primitives', () => {
  it('renders the navbar with search, toggle, and notifications', () => {
    renderWithProviders(<Navbar onMenuClick={jest.fn()} />);

    expect(screen.getByText('Harmony')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search services/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /toggle theme/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open notifications/i })).toBeInTheDocument();
  });

  it('displays all sidebar navigation entries', () => {
    renderWithProviders(<Sidebar open onOpenChange={jest.fn()} />);

    const expectedLinks = ['Dashboard', 'Spotify', 'Plex', 'Soulseek', 'Beets', 'Matching', 'Settings'];

    expectedLinks.forEach((label) => {
      expect(screen.getAllByRole('link', { name: label })[0]).toBeInTheDocument();
    });
  });

  it('shows the dark/light mode toggle inside the composed layout', () => {
    renderWithProviders(
      <Layout>
        <div>layout content</div>
      </Layout>
    );

    const toggleButton = screen.getByRole('button', { name: /toggle theme/i });
    expect(toggleButton).toBeInTheDocument();

    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute('aria-pressed', 'true');
  });
});
