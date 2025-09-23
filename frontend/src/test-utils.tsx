import { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from './lib/query';
import { render } from './testing/dom-testing';
import { ThemeProvider } from './components/theme-provider';
import { ToastContext, ToastMessage } from './hooks/useToast';

interface ExtendedRenderOptions {
  toastFn?: (message: ToastMessage) => void;
  routerEntries?: string[];
}

export const renderWithProviders = (
  ui: ReactNode,
  { toastFn = () => undefined, routerEntries = ['/'] }: ExtendedRenderOptions = {}
) => {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastContext.Provider value={{ toast: toastFn }}>
          <MemoryRouter initialEntries={routerEntries}>{ui}</MemoryRouter>
        </ToastContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>
  );
};
