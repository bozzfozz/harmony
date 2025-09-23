import { ReactNode } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from './lib/query';
import { ThemeProvider } from './components/theme-provider';
import ToastProvider from './components/ToastProvider';
import { ToastMessage } from './hooks/useToast';

export interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  toastFn?: (message: ToastMessage) => void;
  route?: string;
}

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
        <ToastProvider onToast={toastFn}>
          <BrowserRouter>{children}</BrowserRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );

  return render(<>{ui}</>, { wrapper: Wrapper, ...renderOptions });
};
