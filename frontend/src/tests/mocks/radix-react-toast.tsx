import * as React from 'react';

type ToastContextValue = {
  onOpenChange?: (open: boolean) => void;
};

const ToastContext = React.createContext<ToastContextValue>({});

export interface ToastProviderProps {
  children?: React.ReactNode;
  duration?: number;
  swipeDirection?: 'left' | 'right' | 'up' | 'down';
}

export const Provider: React.FC<ToastProviderProps> = ({ children }) => <>{children}</>;

export const Viewport = React.forwardRef<
  HTMLOListElement,
  React.ComponentPropsWithoutRef<'ol'>
>(({ children, ...props }, ref) => (
  <ol ref={ref} {...props}>
    {children}
  </ol>
));

Viewport.displayName = 'ToastViewport';

export interface ToastProps extends React.ComponentPropsWithoutRef<'li'> {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  duration?: number;
}

export const Root = React.forwardRef<HTMLLIElement, ToastProps>(
  ({ children, open = true, onOpenChange, duration, ...props }, ref) => {
    const contextValue = React.useMemo(() => ({ onOpenChange }), [onOpenChange]);
    React.useEffect(() => {
      if (!open || !duration) {
        return;
      }
      const timer = setTimeout(() => {
        onOpenChange?.(false);
      }, duration);
      return () => clearTimeout(timer);
    }, [open, onOpenChange, duration]);

    return (
      <ToastContext.Provider value={contextValue}>
        <li ref={ref} data-open={open ? 'true' : 'false'} {...props}>
          {open ? children : null}
        </li>
      </ToastContext.Provider>
    );
  }
);

Root.displayName = 'Toast';

export const Title = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<'div'>>(
  ({ ...props }, ref) => <div ref={ref} {...props} />
);

Title.displayName = 'ToastTitle';

export const Description = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<'div'>
>(({ ...props }, ref) => <div ref={ref} {...props} />);

Description.displayName = 'ToastDescription';

export const Close = React.forwardRef<HTMLButtonElement, React.ComponentPropsWithoutRef<'button'>>(
  ({ onClick, ...props }, ref) => {
    const { onOpenChange } = React.useContext(ToastContext);
    return (
      <button
        {...props}
        ref={ref}
        onClick={(event) => {
          onOpenChange?.(false);
          onClick?.(event);
        }}
      />
    );
  }
);

Close.displayName = 'ToastClose';

export interface ToastActionProps extends React.ComponentPropsWithoutRef<'button'> {
  altText: string;
}

export const Action = React.forwardRef<HTMLButtonElement, ToastActionProps>(
  ({ altText: _altText, ...props }, ref) => <button ref={ref} {...props} />
);

Action.displayName = 'ToastAction';
