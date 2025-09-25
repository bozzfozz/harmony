import { dismiss, toast as showToast, useToast as useUiToast } from '../components/ui/use-toast';

export interface ToastMessage {
  title: string;
  description?: string;
  variant?: 'default' | 'destructive' | 'success' | 'info';
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
