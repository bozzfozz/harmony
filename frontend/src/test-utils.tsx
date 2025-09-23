import { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RenderOptions, render } from '@testing-library/react';
import { ToastContext, ToastMessage } from './hooks/useToast';

const createWrapper = (toastFn: (message: ToastMessage) => void) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false }
    }
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ToastContext.Provider value={{ toast: toastFn }}>{children}</ToastContext.Provider>
    </QueryClientProvider>
  );
};

export const renderWithProviders = (
  ui: ReactNode,
  { toastFn = () => undefined, ...renderOptions }: RenderOptions & { toastFn?: (message: ToastMessage) => void } = {}
) => {
  const Wrapper = createWrapper(toastFn);
  return render(<>{ui}</>, { wrapper: Wrapper, ...renderOptions });
};
