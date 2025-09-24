import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const mapProgressToPercent = (value: number) => {
  if (Number.isNaN(value)) {
    return 0;
  }
  if (value < 0) {
    return 0;
  }
  if (value <= 1) {
    return Math.round(value * 100);
  }
  if (value <= 100) {
    return Math.round(value);
  }
  return 100;
};
