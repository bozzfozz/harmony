 main
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
 main
    </ToastContext.Provider>
  );
};

export default ToastProvider;
