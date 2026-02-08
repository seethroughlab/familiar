/**
 * AppHeader - The top header bar with navigation tabs, search, chat toggle, and status indicators.
 */
import { useRef, useState } from 'react';
import { Search, Library, Settings, Zap, MessageSquare, X, ListMusic } from 'lucide-react';
import type { AppTab } from '../utils/urlParams';
import { ColumnSelector } from './Library/ColumnSelector';
import { DownloadIndicator } from './DownloadIndicator';
import { ProposedChangesIndicator } from './ProposedChangesIndicator';
import { BackgroundJobsIndicator } from './BackgroundJobsIndicator';
import { HealthIndicator } from './HealthIndicator';

interface AppHeaderProps {
  rightPanelTab: AppTab;
  setRightPanelTab: (tab: AppTab) => void;
  showChatPanel: boolean;
  setShowChatPanel: (v: boolean | ((prev: boolean) => boolean)) => void;
  setShowMobileChat: (v: boolean) => void;
  showQueuePanel: boolean;
  setShowQueuePanel: (v: boolean | ((prev: boolean) => boolean)) => void;
  search: string;
  setSearch: (v: string) => void;
  resolvedTheme: string;
}

export function AppHeader({
  rightPanelTab,
  setRightPanelTab,
  showChatPanel,
  setShowChatPanel,
  setShowMobileChat,
  showQueuePanel,
  setShowQueuePanel,
  search,
  setSearch,
  resolvedTheme,
}: AppHeaderProps) {
  const [mobileSearchExpanded, setMobileSearchExpanded] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  return (
    <header className={`relative z-30 backdrop-blur-md border-b pt-safe ${resolvedTheme === 'light' ? 'bg-white/80 border-zinc-200' : 'bg-zinc-900/80 border-zinc-800'}`}>
      <div className="px-4 py-3 flex items-center gap-2 md:gap-4">
        {/* Mobile search expanded state - takes over header */}
        {mobileSearchExpanded ? (
          <div className="flex-1 flex items-center gap-2 md:hidden">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
              <input
                ref={searchInputRef}
                type="search"
                inputMode="search"
                placeholder="Search tracks..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onBlur={() => {
                  // Delay to allow tap on X button
                  setTimeout(() => setMobileSearchExpanded(false), 150);
                }}
                className="w-full pl-10 pr-4 py-2 bg-zinc-800 border border-zinc-700 rounded-full text-base placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                aria-label="Search tracks"
                autoFocus
              />
            </div>
            <button
              onClick={() => {
                setSearch('');
                setMobileSearchExpanded(false);
              }}
              className="p-2 rounded-lg text-zinc-400 hover:text-white"
              aria-label="Cancel search"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        ) : (
          <>
            {/* Chat toggle - mobile opens overlay, desktop toggles slide-in panel */}
            <button
              onClick={() => {
                if (window.innerWidth >= 768) {
                  setShowChatPanel((prev: boolean) => !prev);
                } else {
                  setShowMobileChat(true);
                }
              }}
              className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${
                showChatPanel
                  ? 'bg-zinc-800 text-white'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
              }`}
              aria-label={showChatPanel ? 'Close chat' : 'Open chat'}
              title="AI Assistant"
            >
              <MessageSquare className="w-4 h-4 inline-block sm:mr-1.5" />
              <span className="hidden sm:inline">Chat</span>
            </button>

            {/* Tabs */}
            <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Main navigation">
              <button
                onClick={() => setRightPanelTab('library')}
                className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${
                  rightPanelTab === 'library'
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                }`}
                role="tab"
                aria-selected={rightPanelTab === 'library'}
                aria-label="Library"
              >
                <Library className="w-4 h-4 inline-block sm:mr-1.5" />
                <span className="hidden sm:inline">Library</span>
              </button>
              <button
                onClick={() => setRightPanelTab('playlists')}
                className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${
                  rightPanelTab === 'playlists'
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                }`}
                role="tab"
                aria-selected={rightPanelTab === 'playlists'}
                aria-label="Playlists"
              >
                <Zap className="w-4 h-4 inline-block sm:mr-1.5" />
                <span className="hidden sm:inline">Playlists</span>
              </button>
              <button
                onClick={() => {
                  // Desktop: toggle docked panel; Mobile: use tab
                  if (window.innerWidth >= 768) {
                    setShowQueuePanel((prev: boolean) => !prev);
                  } else {
                    setRightPanelTab('queue');
                  }
                }}
                className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${
                  rightPanelTab === 'queue' || showQueuePanel
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                }`}
                role="tab"
                aria-selected={rightPanelTab === 'queue' || showQueuePanel}
                aria-label="Queue"
              >
                <ListMusic className="w-4 h-4 inline-block sm:mr-1.5" />
                <span className="hidden sm:inline">Queue</span>
              </button>
              <button
                onClick={() => setRightPanelTab('settings')}
                className={`px-2 sm:px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap ${
                  rightPanelTab === 'settings'
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-800/50'
                }`}
                role="tab"
                aria-selected={rightPanelTab === 'settings'}
                aria-label="Settings"
              >
                <Settings className="w-4 h-4 inline-block sm:mr-1.5" />
                <span className="hidden sm:inline">Settings</span>
              </button>
            </div>

            {/* Mobile search icon (library view only) */}
            {rightPanelTab === 'library' && (
              <button
                onClick={() => {
                  setMobileSearchExpanded(true);
                  // Focus will happen via autoFocus
                }}
                className="md:hidden p-2 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800/50"
                aria-label="Search"
              >
                <Search className="w-5 h-5" />
              </button>
            )}

            {/* Desktop search and column selector (only in library view) */}
            {rightPanelTab === 'library' && (
              <>
                <div className="hidden md:block flex-1 max-w-md">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
                    <input
                      type="search"
                      placeholder="Search tracks..."
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      className="w-full pl-10 pr-4 py-2 bg-zinc-800 border border-zinc-700 rounded-full text-base placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                      aria-label="Search tracks"
                    />
                  </div>
                </div>
                <div className="hidden md:block">
                  <ColumnSelector />
                </div>
              </>
            )}

            {/* Spacer to push indicators right */}
            <div className="flex-1" />

            {/* Download progress indicator - shows when downloads are in progress */}
            <DownloadIndicator />

            {/* Proposed changes indicator - shows when changes need review */}
            <ProposedChangesIndicator />

            {/* Background jobs indicator - shows when jobs are running */}
            <BackgroundJobsIndicator />

            {/* Health indicator - only shows when issues detected */}
            <HealthIndicator />
          </>
        )}
      </div>
    </header>
  );
}
