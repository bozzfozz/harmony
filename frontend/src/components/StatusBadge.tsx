import { cn } from '../lib/utils';

type StatusTone = 'positive' | 'warning' | 'danger' | 'info';

const toneClasses: Record<StatusTone, string> = {
  positive:
    'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100 border border-emerald-200 dark:border-emerald-700',
  warning:
    'bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100 border border-amber-200 dark:border-amber-700',
  danger:
    'bg-rose-100 text-rose-900 dark:bg-rose-900/40 dark:text-rose-100 border border-rose-200 dark:border-rose-700',
  info:
    'bg-slate-200 text-slate-900 dark:bg-slate-800/70 dark:text-slate-100 border border-slate-300 dark:border-slate-600'
};

const toneIcons: Record<StatusTone, string> = {
  positive: '✅',
  warning: '⚠️',
  danger: '⛔',
  info: 'ℹ️'
};

const titleCase = (value: string): string =>
  value
    .split(/\s+|_|-/u)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');

const inferTone = (value: string): StatusTone => {
  const normalized = value.toLowerCase();
  if (
    [
      'connected',
      'ok',
      'healthy',
      'online',
      'completed',
      'active',
      'running',
      'up',
      'available'
    ].includes(normalized)
  ) {
    return 'positive';
  }
  if (
    [
      'degraded',
      'warning',
      'limited',
      'uploading',
      'pending',
      'queued',
      'starting',
      'partial'
    ].includes(normalized)
  ) {
    return 'warning';
  }
  if (
    ['disconnected', 'down', 'failed', 'error', 'offline', 'cancelled', 'blocked'].includes(normalized)
  ) {
    return 'danger';
  }
  return 'info';
};

export interface StatusBadgeProps {
  status: string;
  label?: string;
  tone?: StatusTone;
  className?: string;
}

const StatusBadge = ({ status, label, tone, className }: StatusBadgeProps) => {
  const resolvedTone = tone ?? inferTone(status);
  const resolvedLabel = label ?? titleCase(status);
  const icon = toneIcons[resolvedTone];

  return (
    <span
      role="status"
      aria-label={`Status: ${resolvedLabel}`}
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium tracking-wide',
        toneClasses[resolvedTone],
        className
      )}
    >
      <span aria-hidden="true">{icon}</span>
      <span>{resolvedLabel}</span>
    </span>
  );
};

export default StatusBadge;
