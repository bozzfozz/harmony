import type { ReactNode } from 'react';

import { cn } from '../lib/utils';

export type MetricTone = 'default' | 'positive' | 'warning' | 'danger' | 'info';

const toneClasses: Record<MetricTone, string> = {
  default: 'text-slate-900 dark:text-slate-100',
  positive: 'text-emerald-600 dark:text-emerald-300',
  warning: 'text-amber-600 dark:text-amber-300',
  danger: 'text-rose-600 dark:text-rose-300',
  info: 'text-sky-600 dark:text-sky-300'
};

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: MetricTone;
  className?: string;
}

const MetricCard = ({ label, value, hint, tone = 'default', className }: MetricCardProps) => (
  <div
    className={cn(
      'rounded-lg border border-slate-200 bg-white/60 p-4 shadow-sm backdrop-blur-sm dark:border-slate-700 dark:bg-slate-900/40',
      className
    )}
  >
    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
    <div className={cn('mt-2 text-2xl font-semibold', toneClasses[tone])}>{value}</div>
    {hint ? <p className="mt-2 text-sm text-muted-foreground">{hint}</p> : null}
  </div>
);

export default MetricCard;
