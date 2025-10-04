import { Toast, ToastClose, ToastDescription, ToastTitle, ToastViewport } from './toast';
import { useToast } from './use-toast';

const Toaster = () => {
  const { toasts } = useToast();

  return (
    <>
      {toasts.map(({ id, title, description, action, variant, open, duration, onOpenChange }) => (
        <Toast
          key={id}
          open={open}
          onOpenChange={onOpenChange}
          duration={duration}
          variant={variant}
        >
          <div className="grid gap-1">
            {title ? <ToastTitle>{title}</ToastTitle> : null}
            {description ? <ToastDescription>{description}</ToastDescription> : null}
          </div>
          {action ? <div>{action}</div> : null}
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </>
  );
};

export default Toaster;
