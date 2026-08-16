/**
 * Sidebar - Persistent navigation sidebar.
 *
 * Sections: Library browsers, Collections (with counts), Playlists, Smart Playlists, Footer.
 * Right-click context menus on playlist items, collection items, and library items.
 */
import { useState } from 'react';
import { useLocation, Link, useNavigate } from 'react-router-dom';
import {
  House,
  List, Users, Grid3X3, Smile, Map, Activity, Sparkles, FileText,
  Heart, Download, Inbox, Combine,
  Settings, PanelLeftClose, PanelLeft,
} from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { useThemeStore } from '../../stores/themeStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { useContextMenu } from '../../hooks/useContextMenu';
import { CollectionContextMenu } from './CollectionContextMenu';
import { LibraryItemContextMenu } from './LibraryItemContextMenu';
import { ExportMixTapeModal } from '../MixTape';

import { HOME_ROUTE, LIBRARY_ITEMS as LIBRARY_ITEM_DEFS } from '../../routes';

const LIBRARY_ICON_MAP: Record<string, typeof List> = {
  '/library/tracks': List,
  '/library/artists': Users,
  '/library/albums': Grid3X3,
  '/library/mood-grid': Smile,
  '/library/music-map': Map,
  '/library/explorer': Activity,
  '/library/discover': Sparkles,
  '/library/proposed-changes': FileText,
  '/library/pending-review': Inbox,
  '/library/artist-cleanup': Combine,
};

const LIBRARY_ITEMS = LIBRARY_ITEM_DEFS.map((item) => ({
  ...item,
  icon: LIBRARY_ICON_MAP[item.path] ?? List,
}));

const COLLECTION_ITEMS = [
  { path: '/favorites', label: 'Favorites', icon: Heart, countKey: 'favorites' as const },
  { path: '/downloads', label: 'Downloads', icon: Download, countKey: 'downloads' as const },
];

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useUIStore((s) => s.setSidebarCollapsed);

  // Section collapse state

  // Context menu state
  const collectionMenu = useContextMenu<string>(); // stores collection path
  const libraryMenu = useContextMenu<string>(); // stores library item path

  // Playlist edit modal

  // Smart playlist builder
  const [mixtapeSource, setMixtapeSource] = useState<
    | { kind: 'playlist'; id: string; defaultName: string }
    | { kind: 'smart_playlist'; id: string; defaultName: string }
    | null
  >(null);

  // Collection counts
  const { total: favoritesCount } = useFavorites();
  const { total: downloadsCount } = useDownloadedTracks();


  const counts = {
    favorites: favoritesCount,
    downloads: downloadsCount,
  };



  const isActive = (path: string) => {
    if (path === '/library/artists') {
      // Also match artist detail routes
      return location.pathname === path || location.pathname.startsWith('/library/artists/');
    }
    if (path === '/library/albums') {
      return location.pathname === path || location.pathname.startsWith('/library/albums/');
    }
    return location.pathname === path;
  };

  const light = resolvedTheme === 'light';
  const bgClass = light ? 'bg-zinc-50 border-zinc-200' : 'bg-zinc-950 border-zinc-800';
  const hoverClass = light ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800';
  const activeClass = light ? 'bg-zinc-200 text-zinc-900' : 'bg-zinc-800 text-white';
  const textClass = light ? 'text-zinc-600' : 'text-zinc-400';
  const sectionClass = light ? 'text-zinc-400' : 'text-zinc-500';
  const dividerClass = light ? 'border-zinc-200' : 'border-zinc-800';

  // Collapsed sidebar (icon-only)
  if (sidebarCollapsed) {
    return (
      <div className={`w-14 flex flex-col border-r ${bgClass} h-full`}>
        <div className="flex-1 py-2 space-y-0.5 overflow-y-auto">
          <Link
            to={HOME_ROUTE.path}
            className={`flex items-center justify-center mx-1 p-2 rounded-lg transition-colors ${
              isActive(HOME_ROUTE.path) ? activeClass : `${textClass} ${hoverClass}`
            }`}
            title={HOME_ROUTE.label}
          >
            <House className="w-5 h-5" />
          </Link>
          <div className={`mx-3 my-2 border-t ${dividerClass}`} />
          {LIBRARY_ITEMS.map((item) => (
            <div key={item.path} onContextMenu={(e) => libraryMenu.open(item.path, e)}>
              <Link
                to={item.path}
                className={`flex items-center justify-center mx-1 p-2 rounded-lg transition-colors ${
                  isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
                }`}
                title={item.label}
              >
                <item.icon className="w-5 h-5" />
              </Link>
            </div>
          ))}
          <div className={`mx-3 my-2 border-t ${dividerClass}`} />
          {COLLECTION_ITEMS.map((item) => (
            <div key={item.path} onContextMenu={(e) => collectionMenu.open(item.path, e)}>
              <Link
                to={item.path}
                className={`flex items-center justify-center mx-1 p-2 rounded-lg transition-colors ${
                  isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
                }`}
                title={`${item.label} (${counts[item.countKey]})`}
              >
                <item.icon className="w-5 h-5" />
              </Link>
            </div>
          ))}
        </div>
        <div className={`border-t p-1 space-y-0.5 ${dividerClass}`}>
          <button
            onClick={() => navigate('/settings')}
            className={`flex items-center justify-center w-full p-2 rounded-lg ${textClass} ${hoverClass}`}
            title="Settings"
          >
            <Settings className="w-5 h-5" />
          </button>
          <button
            onClick={() => setSidebarCollapsed(false)}
            className={`flex items-center justify-center w-full p-2 rounded-lg ${textClass} ${hoverClass}`}
            title="Expand sidebar"
          >
            <PanelLeft className="w-5 h-5" />
          </button>
        </div>

        {/* Context menus (rendered even when collapsed) */}
        {libraryMenu.state.isOpen && libraryMenu.state.item && (
          <LibraryItemContextMenu
            path={libraryMenu.state.item}
            position={libraryMenu.state.position}
            onClose={libraryMenu.close}
          />
        )}
        {collectionMenu.state.isOpen && collectionMenu.state.item && (
          <CollectionContextMenu
            collectionPath={collectionMenu.state.item}
            position={collectionMenu.state.position}
            onClose={collectionMenu.close}
          />
        )}
      </div>
    );
  }

  // Expanded sidebar
  return (
    <div className={`w-60 flex flex-col border-r ${bgClass} h-full`}>
      <div className="flex-1 overflow-y-auto min-h-0 py-2">
        <div className="px-2">
          <Link
            to={HOME_ROUTE.path}
            className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
              isActive(HOME_ROUTE.path) ? activeClass : `${textClass} ${hoverClass}`
            }`}
          >
            <House className="w-4 h-4 flex-shrink-0" />
            <span className="truncate flex-1">{HOME_ROUTE.label}</span>
          </Link>
        </div>

        <div className={`mx-4 my-3 border-t ${dividerClass}`} />

        {/* Library section */}
        <div className={`px-4 py-1 text-xs font-semibold uppercase tracking-wider ${sectionClass}`}>
          Library
        </div>
        <nav className="space-y-0.5 px-2 mt-1">
          {LIBRARY_ITEMS.map((item) => (
            <div key={item.path} onContextMenu={(e) => libraryMenu.open(item.path, e)}>
              <Link
                to={item.path}
                className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
                  isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
                }`}
              >
                <item.icon className="w-4 h-4 flex-shrink-0" />
                <span className="truncate flex-1">{item.label}</span>
              </Link>
            </div>
          ))}
        </nav>

        <div className={`mx-4 my-3 border-t ${dividerClass}`} />

        {/* Collections section */}
        <div className={`px-4 py-1 text-xs font-semibold uppercase tracking-wider ${sectionClass}`}>
          Collections
        </div>
        <nav className="space-y-0.5 px-2 mt-1">
          {COLLECTION_ITEMS.map((item) => (
            <div key={item.path} onContextMenu={(e) => collectionMenu.open(item.path, e)}>
              <Link
                to={item.path}
                className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
                  isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
                }`}
              >
                <item.icon className="w-4 h-4 flex-shrink-0" />
                <span className="truncate flex-1">{item.label}</span>
                {counts[item.countKey] > 0 && (
                  <span className={`text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
                    {counts[item.countKey]}
                  </span>
                )}
              </Link>
            </div>
          ))}
        </nav>

      </div>

      {/* Footer */}
      <div className={`border-t p-2 ${dividerClass}`}>
        <div className="space-y-0.5">
          <button
            onClick={() => navigate('/settings')}
            className={`flex items-center gap-3 w-full px-2 py-1.5 rounded-lg text-sm transition-colors ${textClass} ${hoverClass}`}
          >
            <Settings className="w-4 h-4" />
            <span>Settings</span>
          </button>
          <button
            onClick={() => setSidebarCollapsed(true)}
            className={`flex items-center gap-3 w-full px-2 py-1.5 rounded-lg text-sm transition-colors ${textClass} ${hoverClass}`}
          >
            <PanelLeftClose className="w-4 h-4" />
            <span>Collapse</span>
          </button>
        </div>
      </div>

      {/* Context menus */}
      {mixtapeSource && (
        <ExportMixTapeModal
          isOpen={true}
          onClose={() => setMixtapeSource(null)}
          source={mixtapeSource}
        />
      )}
      {collectionMenu.state.isOpen && collectionMenu.state.item && (
        <CollectionContextMenu
          collectionPath={collectionMenu.state.item}
          position={collectionMenu.state.position}
          onClose={collectionMenu.close}
        />
      )}
      {libraryMenu.state.isOpen && libraryMenu.state.item && (
        <LibraryItemContextMenu
          path={libraryMenu.state.item}
          position={libraryMenu.state.position}
          onClose={libraryMenu.close}
        />
      )}

      {/* Smart playlist builder */}

      {/* Edit modal */}
    </div>
  );
}
