import { ReactNode } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { useEffect, useRef } from 'react';
import { QueryClient, QueryClientProvider } from './lib/query';
import { ThemeProvider } from './components/theme-provider';
import { ToastMessage, useToast } from './hooks/useToast';
import Toaster from './components/ui/toaster';
import ApiErrorListener from './components/ApiErrorListener';

export interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  toastFn?: (message: ToastMessage) => void;
  route?: string;
}

const TestToastRecorder = ({ onToast }: { onToast?: (message: ToastMessage) => void }) => {
  const { toasts } = useToast();
  const lastToastId = useRef<string | null>(null);

  useEffect(() => {
    if (!onToast || toasts.length === 0) {
      return;
    }
    const latest = toasts[toasts.length - 1];
    if (!latest || latest.id === lastToastId.current) {
      return;
    }
    lastToastId.current = latest.id;
    const title = typeof latest.title === 'string' ? latest.title : String(latest.title ?? '');
    const description =
      typeof latest.description === 'string'
        ? latest.description
        : latest.description
          ? String(latest.description)
          : undefined;
    const variant = (latest.variant as ToastMessage['variant']) ?? 'default';
    onToast({ title, description, variant });
  }, [onToast, toasts]);

  return null;
};

export const renderWithProviders = (
  ui: ReactNode,
  { toastFn, route = '/', ...renderOptions }: RenderWithProvidersOptions = {}
) => {
  if (route) {
    window.history.pushState({}, 'Test page', route);
  }

  const queryClient = new QueryClient();

  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <ApiErrorListener />
          <Toaster />
          <TestToastRecorder onToast={toastFn} />
          {children}
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );

  return render(<>{ui}</>, { wrapper: Wrapper, ...renderOptions });
};
