import { createContext, useContext } from 'react';

export interface ToastMessage {
  title: string;
  description?: string;
  variant?: 'default' | 'destructive';
}

export interface ToastContextValue {
  toast: (message: ToastMessage) => void;
}

export const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
