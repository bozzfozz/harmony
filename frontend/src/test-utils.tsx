import { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RenderOptions, render } from '@testing-library/react';
import { ThemeProvider } from './components/theme-provider';
import { ToastContext, ToastMessage } from './hooks/useToast';

interface ExtendedRenderOptions extends RenderOptions {
  toastFn?: (message: ToastMessage) => void;
  routerEntries?: string[];
}

const createWrapper = (toastFn: (message: ToastMessage) => void, routerEntries: string[]) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false }
    }
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastContext.Provider value={{ toast: toastFn }}>
          <MemoryRouter initialEntries={routerEntries}>{children}</MemoryRouter>
        </ToastContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>
  );
};

export const renderWithProviders = (
  ui: ReactNode,
  { toastFn = () => undefined, routerEntries = ['/'], ...renderOptions }: ExtendedRenderOptions = {}
) => {
  const Wrapper = createWrapper(toastFn, routerEntries);
  return render(<>{ui}</>, { wrapper: Wrapper, ...renderOptions });
};
