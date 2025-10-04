import { act, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '../test-utils';
import { dismiss, toast } from '../components/ui/use-toast';

describe('toast lifecycle', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it('shows a toast when triggered', async () => {
    renderWithProviders(<div />);

    act(() => {
      toast({ title: 'Hello toast', description: 'Greetings from Harmony' });
    });

    expect(await screen.findByText('Hello toast')).toBeInTheDocument();
    expect(screen.getByText('Greetings from Harmony')).toBeInTheDocument();
  });

  it('dismisses a toast explicitly', async () => {
    renderWithProviders(<div />);

    let id = '';
    act(() => {
      id = toast({ title: 'Dismiss me' });
    });

    expect(await screen.findByText('Dismiss me')).toBeInTheDocument();

    act(() => {
      dismiss(id);
      jest.advanceTimersByTime(0);
    });

    await waitFor(() => {
      expect(screen.queryByText('Dismiss me')).not.toBeInTheDocument();
    });
  });

  it('auto closes a toast after its duration', async () => {
    renderWithProviders(<div />);

    act(() => {
      toast({ title: 'Auto close', duration: 500 });
    });

    expect(await screen.findByText('Auto close')).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(500);
    });

    await waitFor(() => {
      expect(screen.queryByText('Auto close')).not.toBeInTheDocument();
    });
  });
});
