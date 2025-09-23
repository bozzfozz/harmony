import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { ToastContext, ToastMessage } from '../hooks/useToast';
import { cn } from '../lib/utils';

interface ToastProviderProps {
  children: ReactNode;
}

const ToastProvider = ({ children }: ToastProviderProps) => {
  const [open, setOpen] = useState(false);
  const [toastState, setToastState] = useState<ToastMessage | null>(null);

  const toast = useCallback((message: ToastMessage) => {
    setToastState(message);
    setOpen(true);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    const timeout = window.setTimeout(() => setOpen(false), 4000);
    return () => window.clearTimeout(timeout);
  }, [open]);

  const toastContent = useMemo(() => {
    if (!open || !toastState) {
      return null;
    }

    const containerClass = cn(
      'pointer-events-auto flex w-[320px] flex-col gap-1 rounded-lg border bg-background p-4 shadow-lg',
      toastState.variant === 'destructive' && 'border-destructive bg-destructive/10 text-destructive-foreground'
    );

    return (
      <div className={containerClass} role="status">
        {toastState.title ? (
          <p className="text-sm font-semibold">{toastState.title}</p>
        ) : null}
        {toastState.description ? (
          <p className="text-xs text-muted-foreground">{toastState.description}</p>
        ) : null}
      </div>
    );
  }, [open, toastState]);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {createPortal(
        <div className="fixed bottom-4 right-4 z-[100] flex max-h-screen w-full flex-col gap-2 p-4 sm:max-w-[420px]">
          {toastContent}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
};

export default ToastProvider;
