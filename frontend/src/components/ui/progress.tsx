import * as React from 'react';
import { cn } from '../../lib/utils';

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number;
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, ...props }, ref) => (
    <div ref={ref} className={cn('relative h-2 w-full overflow-hidden rounded-full bg-muted', className)} {...props}>
      <div
        className="h-full w-full flex-1 bg-primary transition-all"
        style={{ transform: `translateX(-${Math.max(0, Math.min(100, 100 - value))}%)` }}
        aria-hidden="true"
      />
    </div>
  )
);
Progress.displayName = 'Progress';

export { Progress };
