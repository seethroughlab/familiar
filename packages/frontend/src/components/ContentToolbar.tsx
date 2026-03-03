/**
 * ContentToolbar - Context-sensitive toolbar above the main content area.
 *
 * Shows search bar for library views, and column selector.
 * Renders status indicators that were previously in the header.
 */
import { useState, useRef } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { Search, X } from 'lucide-react';
import { ColumnSelector } from './Library/ColumnSelector';
import { useThemeStore } from '../stores/themeStore';
import { HealthIndicator } from './HealthIndicator';
import { BackgroundJobsIndicator } from './BackgroundJobsIndicator';
import { DownloadIndicator } from './DownloadIndicator';
import { ProposedChangesIndicator } from './ProposedChangesIndicator';

export function ContentToolbar() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const [mobileSearchExpanded, setMobileSearchExpanded] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const isLibraryView = location.pathname.startsWith('/library/');
  const searchValue = searchParams.get('search') || '';

  const updateSearch = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set('search', value);
    } else {
      next.delete('search');
    }
    setSearchParams(next, { replace: true });
  };

  const light = resolvedTheme === 'light';

  const indicators = (
    <div className="flex items-center gap-1">
      <DownloadIndicator />
      <ProposedChangesIndicator />
      <BackgroundJobsIndicator />
      <HealthIndicator />
    </div>
  );

  // Non-library views: just show indicators row
  if (!isLibraryView) {
    return (
      <div className={`pt-safe md:pt-0 px-4 py-2 flex items-center justify-end border-b ${light ? 'border-zinc-200 bg-white/80' : 'border-zinc-800/50 bg-zinc-900/80'} backdrop-blur-sm`}>
        {indicators}
      </div>
    );
  }

  return (
    <div className={`pt-safe md:pt-0 px-4 py-2 flex items-center gap-2 border-b ${light ? 'border-zinc-200 bg-white/80' : 'border-zinc-800/50 bg-zinc-900/80'} backdrop-blur-sm`}>
      {/* Mobile search expanded */}
      {mobileSearchExpanded ? (
        <div className="flex-1 flex items-center gap-2 md:hidden">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
            <input
              ref={searchInputRef}
              type="search"
              inputMode="search"
              placeholder="Search tracks..."
              value={searchValue}
              onChange={(e) => updateSearch(e.target.value)}
              onBlur={() => setTimeout(() => setMobileSearchExpanded(false), 150)}
              className={`w-full pl-10 pr-4 py-1.5 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-green-500 ${
                light ? 'bg-zinc-100 border border-zinc-200 placeholder-zinc-400' : 'bg-zinc-800 border border-zinc-700 placeholder-zinc-500'
              }`}
              autoFocus
            />
          </div>
          <button
            onClick={() => {
              updateSearch('');
              setMobileSearchExpanded(false);
            }}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <>
          {/* Mobile search button */}
          <button
            onClick={() => setMobileSearchExpanded(true)}
            className="md:hidden p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800/50"
            aria-label="Search"
          >
            <Search className="w-4 h-4" />
          </button>

          {/* Desktop search */}
          <div className="hidden md:block flex-1 max-w-sm">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
              <input
                type="search"
                placeholder="Search tracks..."
                value={searchValue}
                onChange={(e) => updateSearch(e.target.value)}
                className={`w-full pl-9 pr-4 py-1.5 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-green-500 ${
                  light ? 'bg-zinc-100 border border-zinc-200 placeholder-zinc-400' : 'bg-zinc-800 border border-zinc-700 placeholder-zinc-500'
                }`}
              />
            </div>
          </div>

          {/* Column selector */}
          <div className="hidden md:block">
            <ColumnSelector />
          </div>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Status indicators */}
          {indicators}
        </>
      )}
    </div>
  );
}
