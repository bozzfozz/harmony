import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { ToastContext, ToastMessage } from '../hooks/useToast';
import { cn } from '../lib/utils';

interface ToastProviderProps {
  children: ReactNode;
  onToast?: (message: ToastMessage) => void;
}

const ToastProvider = ({ children, onToast }: ToastProviderProps) => {
  const [open, setOpen] = useState(false);
  const [toastState, setToastState] = useState<ToastMessage | null>(null);

  const toast = useCallback(
    (message: ToastMessage) => {
      setToastState(message);
      setOpen(true);
      onToast?.(message);
    },
    [onToast]
  );

  useEffect(() => {
    if (!open) {
      return;
    }
    const timer = window.setTimeout(() => setOpen(false), 4000);
    return () => window.clearTimeout(timer);
  }, [open]);

  const portalContent = useMemo(() => {
    if (!open || !toastState || typeof document === 'undefined') {
      return null;
    }

    const { title, description, variant = 'default' } = toastState;
    return createPortal(
      <div className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2">
        <div
          className={cn(
            'relative rounded-md border bg-background p-4 pr-10 text-sm shadow-lg transition-opacity',
            variant === 'destructive' && 'border-destructive bg-destructive text-destructive-foreground'
          )}
        >
          <strong className="block text-sm font-semibold">{title}</strong>
          {description ? <p className="mt-1 text-sm opacity-90">{description}</p> : null}
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="absolute right-2 top-2 inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground hover:bg-muted"
            aria-label="Dismiss toast"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>,
      document.body
    );
  }, [open, toastState]);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {portalContent}
    </ToastContext.Provider>
  );
};

export default ToastProvider;
