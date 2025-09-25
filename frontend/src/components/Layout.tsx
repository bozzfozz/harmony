import { ReactNode, useMemo, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { CircleDot, Download, Menu, Moon, Settings, Sun, Users } from 'lucide-react';
import { cn } from '../lib/utils';
import { Button } from './ui/button';
import { ScrollArea } from './ui/scroll-area';
import { Switch } from './ui/switch';
import { useTheme } from '../hooks/useTheme';

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: CircleDot },
  { to: '/downloads', label: 'Downloads', icon: Download },
  { to: '/artists', label: 'Artists', icon: Users },
  { to: '/settings', label: 'Settings', icon: Settings }
] as const;

interface LayoutProps {
  children: ReactNode;
}

const Layout = ({ children }: LayoutProps) => {
  const { theme, setTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  const activeTitle = useMemo(() => {
    const match = navItems.find((item) => location.pathname.startsWith(item.to));
    return match?.label ?? 'Harmony';
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-64 border-r border-slate-200 bg-white/90 shadow-lg backdrop-blur transition-transform dark:border-slate-800 dark:bg-slate-900/90 lg:static lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
          'lg:block'
        )}
      >
        <div className="flex h-16 items-center px-6">
          <Link to="/dashboard" className="flex items-center gap-2 text-lg font-semibold">
            <CircleDot className="h-5 w-5 text-indigo-600" />
            Harmony
          </Link>
        </div>
        <ScrollArea className="h-[calc(100vh-4rem)]">
          <nav className="flex flex-col gap-1 p-4">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-50',
                      isActive && 'bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-50'
                    )
                  }
                  onClick={() => setSidebarOpen(false)}
                >
                  <Icon className="h-5 w-5" />
                  {item.label}
                </NavLink>
              );
            })}
          </nav>
        </ScrollArea>
      </aside>
      <div className="flex flex-1 flex-col lg:ml-64">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur transition-colors dark:border-slate-800 dark:bg-slate-900/80">
          <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setSidebarOpen((value) => !value)}
              aria-label="Navigation umschalten"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <div className="flex flex-1 items-center justify-between gap-4">
              <div className="flex flex-col">
                <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{activeTitle}</h1>
                <p className="text-xs text-slate-500 dark:text-slate-400">Harmony media orchestrator</p>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 dark:border-slate-700">
                  <Sun className="h-4 w-4 text-slate-500 dark:text-slate-400" />
                  <Switch
                    checked={theme === 'dark'}
                    onCheckedChange={(checked) => setTheme(checked ? 'dark' : 'light')}
                    aria-label="Theme wechseln"
                  />
                  <Moon className="h-4 w-4 text-slate-500 dark:text-slate-400" />
                </div>
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 bg-slate-50/40 px-4 py-6 dark:bg-slate-950/60 md:px-8">
          <div className="mx-auto flex max-w-7xl flex-col gap-6">{children}</div>
        </main>
      </div>
    </div>
  );
};

export default Layout;
