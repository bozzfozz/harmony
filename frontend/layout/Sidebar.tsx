import { Fragment, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Music,
  Radio,
  Sparkles,
  Settings,
  X
} from 'lucide-react';

const navigationItems = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/spotify', label: 'Spotify', icon: Music },
  { to: '/soulseek', label: 'Soulseek', icon: Radio },
  { to: '/matching', label: 'Matching', icon: Sparkles },
  { to: '/settings', label: 'Settings', icon: Settings }
] as const;

export interface SidebarProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const Sidebar = ({ open, onOpenChange }: SidebarProps) => {
  const renderNavigation = (closeOnNavigate?: () => void) => (
    <nav className="flex flex-col gap-1">
      {navigationItems.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              [
                'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-150',
                'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800/70 dark:hover:text-slate-50',
                isActive
                  ? 'bg-slate-900 text-white shadow-sm dark:bg-indigo-500/80 dark:text-white'
                  : 'bg-transparent'
              ].join(' ')
            }
            onClick={closeOnNavigate}
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-600 transition group-hover:bg-indigo-100 group-hover:text-indigo-600 dark:bg-slate-800/70 dark:text-slate-300 dark:group-hover:bg-indigo-500/20 dark:group-hover:text-indigo-200">
              <Icon className="h-4 w-4" />
            </span>
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );

  useEffect(() => {
    if (!open) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onOpenChange(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onOpenChange]);

  const mobileDrawer =
    open &&
    createPortal(
      <div className="fixed inset-0 z-40 flex">
        <button
          type="button"
          className="absolute inset-0 h-full w-full bg-slate-900/50 backdrop-blur-sm"
          aria-label="Close navigation"
          onClick={() => onOpenChange(false)}
        />
        <div
          role="dialog"
          aria-modal="true"
          className="relative ml-0 flex h-full w-72 max-w-full translate-x-0 flex-col border-r border-slate-200 bg-white/95 p-6 shadow-xl transition-transform duration-300 ease-out dark:border-slate-800 dark:bg-slate-950/95"
        >
          <div className="mb-6 flex items-center justify-between">
            <span className="text-lg font-semibold text-slate-900 dark:text-slate-100">Harmony</span>
            <button
              type="button"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-white dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100 dark:focus:ring-offset-slate-950"
              aria-label="Close navigation"
              onClick={() => onOpenChange(false)}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto pr-1">{renderNavigation(() => onOpenChange(false))}</div>
        </div>
      </div>,
      document.body
    );

  return (
    <Fragment>
      <aside className="hidden w-72 flex-col border-r border-slate-200/80 bg-white/80 px-6 py-8 shadow-sm dark:border-slate-800/70 dark:bg-slate-950/70 lg:flex">
        <div className="mb-8">
          <NavLink
            to="/dashboard"
            className="flex items-center gap-3 text-lg font-semibold text-slate-900 transition-colors hover:text-slate-700 dark:text-slate-100 dark:hover:text-slate-300"
          >
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 text-lg font-bold text-white dark:bg-indigo-500/80 dark:text-white">
              H
            </span>
            Harmony
          </NavLink>
        </div>
        <div className="flex-1 space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">Navigation</p>
          </div>
          {renderNavigation()}
        </div>
      </aside>
      {mobileDrawer}
    </Fragment>
  );
};

export default Sidebar;
