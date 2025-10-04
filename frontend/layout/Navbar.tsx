import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell, Menu, Moon, Search, Sun } from 'lucide-react';

import { ApiError } from '../src/api/client';
import { searchSpotify } from '../src/api/services/spotify';
import type { SpotifySearchResults } from '../src/api/services/spotify';
import SearchResultsOverlay from '../src/components/SearchResultsOverlay';
import { useTheme } from '../src/hooks/useTheme';
import { Input } from '../src/components/ui/input';
import { cn } from '../src/lib/utils';

export interface NavbarProps {
  onMenuClick?: () => void;
}

const Navbar = ({ onMenuClick }: NavbarProps) => {
  const { theme, setTheme } = useTheme();
  const [searchTerm, setSearchTerm] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<SpotifySearchResults | null>(null);
  const [isOverlayOpen, setIsOverlayOpen] = useState(false);
  const [activeQuery, setActiveQuery] = useState('');
  const requestIdRef = useRef(0);
  const isDark = theme === 'dark';

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = searchTerm.trim();
    if (!trimmed) {
      setInputError('Please enter a search term.');
      setSearchError(null);
      setResults(null);
      setIsOverlayOpen(false);
      setActiveQuery('');
      return;
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setIsSearching(true);
    setInputError(null);
    setSearchError(null);
    setIsOverlayOpen(true);
    setActiveQuery(trimmed);

    searchSpotify(trimmed)
      .then((data) => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setResults(data);
        setSearchError(null);
      })
      .catch((error) => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        const message = error instanceof ApiError ? error.message || 'Unable to load search results.' : null;
        setSearchError(message ?? 'Unable to load search results.');
        setResults(null);
      })
      .finally(() => {
        if (requestIdRef.current === requestId) {
          setIsSearching(false);
        }
      });
  };

  useEffect(() => {
    if (searchTerm.trim().length === 0) {
      setResults(null);
      setSearchError(null);
      setIsOverlayOpen(false);
      setActiveQuery('');
    }
  }, [searchTerm]);

  const toggleTheme = () => {
    setTheme(isDark ? 'light' : 'dark');
  };

  const inputErrorId = inputError ? 'navbar-search-error' : undefined;

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur-md dark:border-slate-800/70 dark:bg-slate-950/80">
      <div className="relative flex h-16 items-center gap-4 px-4 sm:px-6">
        <button
          type="button"
          onClick={onMenuClick}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-white dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100 dark:focus:ring-offset-slate-950 lg:hidden"
          aria-label="Open navigation menu"
        >
          <Menu className="h-5 w-5" />
        </button>

        <Link
          to="/dashboard"
          className="flex items-center gap-2 text-xl font-semibold tracking-tight text-slate-900 transition-colors hover:text-slate-700 dark:text-slate-100 dark:hover:text-slate-300"
        >
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 text-lg font-bold text-white dark:bg-indigo-500/80 dark:text-white">
            H
          </span>
          Harmony
        </Link>

        <form onSubmit={handleSubmit} className="relative hidden flex-1 items-center md:flex" role="search">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            type="search"
            value={searchTerm}
            onChange={(event) => {
              setSearchTerm(event.target.value);
              if (inputError) {
                setInputError(null);
              }
            }}
            placeholder="Search services, libraries, media..."
            className="h-10 rounded-lg border border-slate-200 bg-white pl-10 pr-4 text-sm text-slate-700 shadow-sm transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-400 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:placeholder:text-slate-500"
            aria-label="Search"
            aria-invalid={inputError ? 'true' : undefined}
            aria-describedby={inputErrorId}
          />
          <SearchResultsOverlay
            query={activeQuery}
            isOpen={isOverlayOpen}
            isLoading={isSearching}
            error={searchError}
            results={results}
            onSelect={() => {
              setIsOverlayOpen(false);
              setResults(null);
            }}
            onClose={() => {
              setIsOverlayOpen(false);
            }}
          />
        </form>

        {inputError ? (
          <p
            id={inputErrorId}
            className="absolute left-1/2 top-16 hidden w-full -translate-x-1/2 text-xs text-red-600 md:block"
            role="alert"
          >
            {inputError}
          </p>
        ) : null}

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={toggleTheme}
            className={cn(
              'inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:border-indigo-400 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-white dark:border-slate-700 dark:text-slate-200 dark:hover:border-indigo-400/70 dark:hover:text-slate-50 dark:focus:ring-offset-slate-950',
              'bg-white/80 dark:bg-slate-900/60'
            )}
            aria-pressed={isDark}
            aria-label="Toggle theme"
          >
            {isDark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            <span className="hidden sm:inline">{isDark ? 'Dark' : 'Light'} mode</span>
          </button>

          <button
            type="button"
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white/80 text-slate-500 transition-colors hover:border-indigo-400 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 focus:ring-offset-white dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300 dark:hover:border-indigo-400/70 dark:hover:text-slate-100 dark:focus:ring-offset-slate-950"
            aria-label="Open notifications"
          >
            <Bell className="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>
  );
};

export default Navbar;
