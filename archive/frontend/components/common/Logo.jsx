import React from "react";

export default function Logo({ onClick, className = "" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center space-x-2 text-lg font-semibold text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 rounded-md ${className}`.trim()}
      aria-label="Porttracker home"
    >
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-indigo-600 text-white font-bold">
        PT
      </span>
      <span className="hidden sm:inline">Porttracker</span>
    </button>
  );
}
