import { ReactNode, useCallback, useState } from 'react';
import * as ToastPrimitive from '@radix-ui/react-toast';
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
    setOpen(false);
    const trigger = () => setOpen(true);
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(trigger);
    } else {
      setTimeout(trigger, 0);
    }
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      <ToastPrimitive.Provider swipeDirection="right">
        {children}
        <ToastPrimitive.Root
          open={open}
          onOpenChange={setOpen}
          className={cn(
            'pointer-events-auto flex w-[320px] flex-col gap-1 rounded-lg border bg-background p-4 shadow-lg',
            toastState?.variant === 'destructive' && 'border-destructive text-destructive-foreground'
          )}
        >
          {toastState?.title ? (
            <ToastPrimitive.Title className="text-sm font-semibold">
              {toastState.title}
            </ToastPrimitive.Title>
          ) : null}
          {toastState?.description ? (
            <ToastPrimitive.Description className="text-xs text-muted-foreground">
              {toastState.description}
            </ToastPrimitive.Description>
          ) : null}
        </ToastPrimitive.Root>
        <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex max-h-screen w-full flex-col gap-2 p-4 sm:max-w-[420px]" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
};

export default ToastProvider;
