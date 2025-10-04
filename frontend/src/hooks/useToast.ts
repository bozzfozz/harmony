import { dismiss, toast as showToast, useToast as useUiToast } from '../components/ui/use-toast';
import type { ToastVariant } from '../components/ui/use-toast';

export interface ToastMessage {
  title: string;
  description?: string;
  variant?: ToastVariant;
}

export const useToast = () => {
  const context = useUiToast();

  return {
    toast: ({ title, description, variant = 'default' }: ToastMessage) =>
      showToast({ title, description, variant }),
    dismiss: context.dismiss,
    toasts: context.toasts
  };
};

export { dismiss };
