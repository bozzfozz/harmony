import * as React from 'react';
import { cn } from '../../lib/utils';

export interface SwitchProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  (
    { className, checked, defaultChecked = false, onCheckedChange, disabled, onClick, onKeyDown, ...props },
    ref
  ) => {
    const [uncontrolled, setUncontrolled] = React.useState(defaultChecked);
    const isControlled = typeof checked === 'boolean';
    const currentChecked = isControlled ? checked : uncontrolled;

    const setChecked = (next: boolean) => {
      if (!isControlled) {
        setUncontrolled(next);
      }
      onCheckedChange?.(next);
    };

    const toggle = () => {
      if (disabled) {
        return;
      }
      setChecked(!currentChecked);
    };

    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={currentChecked}
        data-state={currentChecked ? 'checked' : 'unchecked'}
        aria-disabled={disabled}
        className={cn(
          'peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
          className
        )}
        disabled={disabled}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) {
            toggle();
          }
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented) {
            return;
          }
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggle();
          }
        }}
        {...props}
      >
        <span
          className={cn(
            'pointer-events-none block h-5 w-5 rounded-full bg-background shadow-lg ring-0 transition-transform',
            currentChecked ? 'translate-x-5' : 'translate-x-0'
          )}
          data-state={currentChecked ? 'checked' : 'unchecked'}
        />
      </button>
    );
  }
);
Switch.displayName = 'Switch';

export { Switch };
