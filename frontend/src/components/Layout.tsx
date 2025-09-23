import { ReactNode, useMemo, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import {
  Bell,
  ChevronRight,
  CircleDot,
  Menu,
  RefreshCcw,
  Search,
  Settings,
  Sun,
  Moon,
  Music,
  Radio,
  Disc,
  ListMusic
} from 'lucide-react';
import { useQueryClient } from '../lib/query';
import { cn } from '../lib/utils';
import { Input } from './ui/input';
import { Button } from './ui/button';
import { ScrollArea } from './ui/scroll-area';
import { Switch } from './ui/switch';
import { useTheme } from '../hooks/useTheme';
import { useToast } from '../hooks/useToast';

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: CircleDot },
  { to: '/spotify', label: 'Spotify', icon: Music },
  { to: '/plex', label: 'Plex', icon: Disc },
  { to: '/soulseek', label: 'Soulseek', icon: Radio },
  { to: '/beets', label: 'Beets', icon: ListMusic },
  { to: '/matching', label: 'Matching', icon: ChevronRight },
  { to: '/settings', label: 'Settings', icon: Settings }
];

interface LayoutProps {
  children: ReactNode;
}

const Layout = ({ children }: LayoutProps) => {
  const { theme, setTheme } = useTheme();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const location = useLocation();

  const activeTitle = useMemo(() => {
    const match = navItems.find((item) => location.pathname.startsWith(item.to));
    return match?.label ?? 'Harmony';
  }, [location.pathname]);

  const handleRefresh = async () => {
    await queryClient.invalidateQueries();
    toast({ title: 'Data refreshed', description: 'All panels have been refreshed.' });
  };

  const handleSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    toast({ title: 'Search submitted', description: `You searched for "${searchTerm}".` });
  };

  const renderNavItems = (onNavigate?: () => void) =>
    navItems.map(({ to, label, icon: Icon }) => (
      <NavLink
        key={to}
        to={to}
        onClick={() => onNavigate?.()}
        className={({ isActive }) =>
          cn(
            'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors hover:bg-muted',
            isActive && 'bg-primary/10 text-primary'
          )
        }
      >
        <Icon className="h-4 w-4" />
        {label}
      </NavLink>
    ));

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="hidden w-64 border-r bg-card/60 lg:block">
        <div className="flex h-16 items-center px-6">
          <Link to="/dashboard" className="flex items-center gap-2 text-lg font-semibold">
            <CircleDot className="h-5 w-5 text-primary" />
            Harmony
          </Link>
        </div>
        <ScrollArea className="h-[calc(100vh-4rem)] px-2">
          <nav className="space-y-1 px-4 pb-6">{renderNavItems()}</nav>
        </ScrollArea>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur">
          <div className="flex h-16 items-center gap-4 px-4">
            <Button
              variant="outline"
              size="icon"
              className="lg:hidden"
              onClick={() => setMobileNavOpen(true)}
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-navigation"
            >
              <Menu className="h-4 w-4" />
              <span className="sr-only">Open navigation</span>
            </Button>
            <div className="flex flex-1 items-center gap-4">
              <div>
                <h1 className="text-lg font-semibold">{activeTitle}</h1>
                <p className="text-xs text-muted-foreground">Harmony media orchestrator</p>
              </div>
              <form className="flex flex-1 max-w-xl items-center gap-2" onSubmit={handleSearch}>
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search ports, processes, services..."
                    className="pl-9"
                  />
                </div>
                <Button type="submit" variant="secondary">
                  Search
                </Button>
              </form>
              <div className="flex items-center gap-4">
                <Button variant="outline" size="icon" onClick={handleRefresh}>
                  <RefreshCcw className="h-4 w-4" />
                  <span className="sr-only">Refresh data</span>
                </Button>
                <div className="flex items-center gap-2 rounded-lg border px-3 py-1.5">
                  <Sun className="h-4 w-4 text-muted-foreground" />
                  <Switch
                    checked={theme === 'dark'}
                    onCheckedChange={(checked) => setTheme(checked ? 'dark' : 'light')}
                    aria-label="Toggle theme"
                  />
                  <Moon className="h-4 w-4 text-muted-foreground" />
                </div>
                <Button variant="outline" size="icon">
                  <Bell className="h-4 w-4" />
                  <span className="sr-only">Notifications</span>
                </Button>
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 bg-muted/30 px-4 py-6 md:px-8">{children}</main>
      </div>
      {mobileNavOpen ? (
        <div id="mobile-navigation" className="lg:hidden" role="dialog" aria-modal="true">
          <div
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
          <div className="fixed inset-y-0 left-0 z-50 w-64 bg-card shadow-lg">
            <div className="flex h-16 items-center px-6">
              <Link
                to="/dashboard"
                className="flex items-center gap-2 text-lg font-semibold"
                onClick={() => setMobileNavOpen(false)}
              >
                <CircleDot className="h-5 w-5 text-primary" />
                Harmony
              </Link>
            </div>
            <ScrollArea className="h-[calc(100vh-4rem)] px-4 pb-6">
              <nav className="space-y-1">{renderNavItems(() => setMobileNavOpen(false))}</nav>
            </ScrollArea>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default Layout;
