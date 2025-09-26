import { screen } from '@testing-library/react';

import Layout from '../components/Layout';
import { renderWithProviders } from '../test-utils';

describe('UI smoke test', () => {
  it('renders layout shell without crashing', () => {
    renderWithProviders(
      <Layout>
        <div>Smoke Test</div>
      </Layout>
    );

    expect(screen.getByText('Smoke Test')).toBeInTheDocument();
  });
});
