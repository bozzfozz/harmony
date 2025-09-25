import { X } from 'lucide-react';
import { useToast } from './use-toast';
import { cn } from '../../lib/utils';

const TOAST_RENDER_LIMIT = 3;

const variantStyles: Record<string, string> = {
  default:
    'border-slate-200 bg-white/95 text-slate-700 dark:border-slate-800 dark:bg-slate-900/95 dark:text-slate-200',
  destructive:
    'border-red-500/40 bg-red-500/10 text-red-700 dark:border-red-500/30 dark:bg-red-500/15 dark:text-red-200',
  success:
    'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/15 dark:text-emerald-200',
  info:
    'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/15 dark:text-sky-200'
};

const Toaster = () => {
  const { toasts, dismiss } = useToast();

  return (
    <div className="pointer-events-none fixed top-20 right-4 z-[100] flex w-full max-w-sm flex-col gap-3 p-4 sm:top-16">
      {toasts.slice(-TOAST_RENDER_LIMIT).map((toast) => {
        const variant = toast.variant ?? 'default';
        return (
          <div
            key={toast.id}
            className={cn(
              'pointer-events-auto relative flex flex-col gap-2 rounded-xl border p-4 pr-10 shadow-lg transition-all duration-200',
              variantStyles[variant] ?? variantStyles.default,
              toast.open === false && 'opacity-0'
            )}
          >
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="absolute right-3 top-3 inline-flex h-5 w-5 items-center justify-center rounded-full text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-50"
            >
              <span className="sr-only">Toast schließen</span>
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
            <div className="grid gap-1">
              {toast.title ? (
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{toast.title}</p>
              ) : null}
              {toast.description ? (
                <p className="text-sm text-slate-600 dark:text-slate-300">{toast.description}</p>
              ) : null}
            </div>
            {toast.action ? <div>{toast.action}</div> : null}
          </div>
        );
      })}
    </div>
  );
};

export default Toaster;
