import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground shadow',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        destructive: 'border-transparent bg-destructive text-destructive-foreground shadow',
        outline: 'text-foreground',
        info: 'border-transparent bg-sky-500/10 text-sky-600 dark:text-sky-300',
        success: 'border-transparent bg-emerald-500/10 text-emerald-600 dark:text-emerald-300',
        warning: 'border-transparent bg-amber-500/10 text-amber-600 dark:text-amber-300'
      }
    },
    defaultVariants: {
      variant: 'default'
    }
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  asChild?: boolean;
}

const Badge = React.forwardRef<HTMLDivElement, BadgeProps>(({ className, variant, asChild, ...props }, ref) => {
  const Comp = asChild ? Slot : 'div';
  return <Comp ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />;
});

Badge.displayName = 'Badge';

export { Badge, badgeVariants };
