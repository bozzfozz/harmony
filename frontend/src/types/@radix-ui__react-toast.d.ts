declare module '@radix-ui/react-toast' {
  import * as React from 'react';

  export type SwipeDirection = 'left' | 'right' | 'up' | 'down';

  export interface ToastProviderProps {
    children?: React.ReactNode;
    duration?: number;
    label?: string;
    swipeDirection?: SwipeDirection;
    swipeThreshold?: number;
  }

  export const Provider: React.FC<ToastProviderProps>;

  export interface ToastViewportProps extends React.ComponentPropsWithoutRef<'ol'> {}
  export const Viewport: React.ForwardRefExoticComponent<
    ToastViewportProps & React.RefAttributes<HTMLOListElement>
  >;

  export interface ToastProps extends React.ComponentPropsWithoutRef<'li'> {
    forceMount?: boolean;
    open?: boolean;
    defaultOpen?: boolean;
    duration?: number;
    onOpenChange?: (open: boolean) => void;
  }

  export const Root: React.ForwardRefExoticComponent<ToastProps & React.RefAttributes<HTMLLIElement>>;

  export interface ToastTitleProps extends React.ComponentPropsWithoutRef<'div'> {}
  export const Title: React.ForwardRefExoticComponent<
    ToastTitleProps & React.RefAttributes<HTMLDivElement>
  >;

  export interface ToastDescriptionProps extends React.ComponentPropsWithoutRef<'div'> {}
  export const Description: React.ForwardRefExoticComponent<
    ToastDescriptionProps & React.RefAttributes<HTMLDivElement>
  >;

  export interface ToastCloseProps extends React.ComponentPropsWithoutRef<'button'> {
    asChild?: boolean;
  }
  export const Close: React.ForwardRefExoticComponent<
    ToastCloseProps & React.RefAttributes<HTMLButtonElement>
  >;

  export interface ToastActionProps extends React.ComponentPropsWithoutRef<'button'> {
    asChild?: boolean;
    altText: string;
  }
  export const Action: React.ForwardRefExoticComponent<
    ToastActionProps & React.RefAttributes<HTMLButtonElement>
  >;
}
