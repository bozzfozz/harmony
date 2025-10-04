import { render, screen } from '@testing-library/react';

import StatusBadge from '../components/StatusBadge';

describe('StatusBadge', () => {
  it('renders a danger badge for dead_letter status', () => {
    render(<StatusBadge status="dead_letter" />);

    const badge = screen.getByRole('status', { name: /dead letter/i });
    expect(badge).toHaveClass('bg-rose-100');
    expect(badge).toHaveTextContent('Dead Letter');
    expect(screen.getByText('⛔')).toBeInTheDocument();
  });

  it('normalizes hyphenated dead-letter states to danger', () => {
    render(<StatusBadge status="dead-letter" />);

    const badge = screen.getByRole('status', { name: /dead letter/i });
    expect(badge).toHaveClass('bg-rose-100');
  });

  it('normalizes spaced dead letter states to danger', () => {
    render(<StatusBadge status="dead letter" />);

    const badge = screen.getByRole('status', { name: /dead letter/i });
    expect(badge).toHaveClass('bg-rose-100');
  });

  it('treats short fail aliases as danger', () => {
    render(<StatusBadge status="fail" />);

    const badge = screen.getByRole('status', { name: /fail/i });
    expect(badge).toHaveClass('bg-rose-100');
  });
});
