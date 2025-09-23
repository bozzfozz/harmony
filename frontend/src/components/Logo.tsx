import { memo } from "react";

import { cn } from "../lib/utils";

interface LogoProps {
  className?: string;
}

const Logo = memo(({ className }: LogoProps) => (
  <svg
    role="img"
    aria-label="Harmony logo"
    viewBox="0 0 64 64"
    className={cn("text-indigo-600", className)}
  >
    <defs>
      <linearGradient id="harmonyGradient" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="currentColor" stopOpacity="0.9" />
        <stop offset="100%" stopColor="currentColor" stopOpacity="0.6" />
      </linearGradient>
    </defs>
    <circle cx="32" cy="32" r="30" fill="url(#harmonyGradient)" opacity="0.2" />
    <path
      d="M18 20c0-2.21 1.79-4 4-4h4c2.21 0 4 1.79 4 4v16.3c0 3.52 2.85 6.37 6.37 6.37h5.26c3.52 0 6.37-2.85 6.37-6.37 0-3.51-2.85-6.36-6.37-6.36h-3.26"
      fill="none"
      stroke="currentColor"
      strokeWidth="4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <circle cx="26" cy="44" r="4" fill="currentColor" />
    <circle cx="44" cy="44" r="4" fill="currentColor" />
  </svg>
));
Logo.displayName = "Logo";

export default Logo;
