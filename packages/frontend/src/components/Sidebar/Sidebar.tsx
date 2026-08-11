/**
 * Sidebar - Persistent navigation sidebar.
 *
 * Sections: Library browsers, Collections (with counts), Playlists, Smart Playlists, Footer.
 * Right-click context menus on playlist items, collection items, and library items.
 */
import { useState } from 'react';
import { useLocation, Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  House,
  List, Users, Grid3X3, Smile, Map, Activity, Sparkles, FileText,
  Heart, Download, Inbox, Combine,
  Settings, PanelLeftClose, PanelLeft,
  ChevronDown, ChevronUp, Plus,
} from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { useThemeStore } from '../../stores/themeStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { useContextMenu } from '../../hooks/useContextMenu';
import { playlistsApi, smartPlaylistsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { offlineAwareRetry } from '../../api/queryDefaults';
import type { Playlist, SmartPlaylist } from '../../api';
import { SidebarPlaylistItem } from './SidebarPlaylistItem';
import { PlaylistContextMenu } from './PlaylistContextMenu';
import { SmartPlaylistContextMenu } from './SmartPlaylistContextMenu';
import { PlaylistEditModal } from './PlaylistEditModal';
import { CollectionContextMenu } from './CollectionContextMenu';
import { LibraryItemContextMenu } from './LibraryItemContextMenu';
import { SmartPlaylistBuilder } from '../SmartPlaylists';
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
  const [playlistsExpanded, setPlaylistsExpanded] = useState(true);
  const [smartPlaylistsExpanded, setSmartPlaylistsExpanded] = useState(true);

  // Context menu state
  const playlistMenu = useContextMenu<Playlist>();
  const smartPlaylistMenu = useContextMenu<SmartPlaylist>();
  const collectionMenu = useContextMenu<string>(); // stores collection path
  const libraryMenu = useContextMenu<string>(); // stores library item path

  // Playlist edit modal
  const [editModal, setEditModal] = useState<{ id?: string; name: string; description: string } | null>(null);

  // Smart playlist builder
  const [showSmartPlaylistBuilder, setShowSmartPlaylistBuilder] = useState(false);
  const [editingSmartPlaylist, setEditingSmartPlaylist] = useState<SmartPlaylist | undefined>();
  const [mixtapeSource, setMixtapeSource] = useState<
    | { kind: 'playlist'; id: string; defaultName: string }
    | { kind: 'smart_playlist'; id: string; defaultName: string }
    | null
  >(null);

  // Collection counts
  const { total: favoritesCount } = useFavorites();
  const { total: downloadsCount } = useDownloadedTracks();
  const { isOffline } = useOfflineStatus();

  const counts = {
    favorites: favoritesCount,
    downloads: downloadsCount,
  };

  // Playlists
  const { data: playlists } = useQuery({
    queryKey: queryKeys.playlists.all,
    queryFn: () => playlistsApi.list(true),
    retry: offlineAwareRetry(isOffline),
  });

  // Smart playlists
  const { data: smartPlaylists } = useQuery({
    queryKey: queryKeys.smartPlaylists.all,
    queryFn: () => smartPlaylistsApi.list(),
    retry: offlineAwareRetry(isOffline),
  });

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

  const isPlaylistActive = (id: string) => location.pathname === `/playlists/${id}`;
  const isSmartPlaylistActive = (id: string) => location.pathname === `/smart-playlists/${id}`;

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

        <div className={`mx-4 my-3 border-t ${dividerClass}`} />

        {/* Playlists section */}
        <div className="flex items-center px-4 py-1">
          <button
            onClick={() => setPlaylistsExpanded(!playlistsExpanded)}
            className={`flex items-center gap-1 flex-1 text-xs font-semibold uppercase tracking-wider ${sectionClass} ${hoverClass} rounded py-0.5`}
          >
            <span>Playlists</span>
            {playlistsExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          <button
            onClick={() => setEditModal({ name: '', description: '' })}
            className={`p-0.5 rounded ${sectionClass} ${hoverClass}`}
            title="Create playlist"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
        {playlistsExpanded && (
          <nav className="space-y-0.5 px-2 mt-1">
            {playlists && playlists.length > 0 ? (
              playlists.map((pl) => (
                <SidebarPlaylistItem
                  key={pl.id}
                  id={pl.id}
                  name={pl.name}
                  trackCount={pl.track_count}
                  to={`/playlists/${pl.id}`}
                  isActive={isPlaylistActive(pl.id)}
                  activeClass={activeClass}
                  textClass={textClass}
                  hoverClass={hoverClass}
                  countClass={light ? 'text-zinc-400' : 'text-zinc-500'}
                  onContextMenu={(e) => playlistMenu.open(pl, e)}
                />
              ))
            ) : (
              <div className={`px-2 py-1.5 text-xs ${textClass}`}>
                No playlists yet
              </div>
            )}
          </nav>
        )}

        <div className={`mx-4 my-3 border-t ${dividerClass}`} />

        {/* Smart Playlists section */}
        <div className="flex items-center px-4 py-1">
          <button
            onClick={() => setSmartPlaylistsExpanded(!smartPlaylistsExpanded)}
            className={`flex items-center gap-1 flex-1 text-xs font-semibold uppercase tracking-wider ${sectionClass} ${hoverClass} rounded py-0.5`}
          >
            <span>Smart Playlists</span>
            {smartPlaylistsExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          <button
            onClick={() => setShowSmartPlaylistBuilder(true)}
            className={`p-0.5 rounded ${sectionClass} ${hoverClass}`}
            title="Create smart playlist"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
        {smartPlaylistsExpanded && (
          <nav className="space-y-0.5 px-2 mt-1">
            {smartPlaylists && smartPlaylists.length > 0 ? (
              smartPlaylists.map((pl) => (
                <div key={pl.id} onContextMenu={(e) => smartPlaylistMenu.open(pl, e)}>
                  <Link
                    to={`/smart-playlists/${pl.id}`}
                    className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
                      isSmartPlaylistActive(pl.id) ? activeClass : `${textClass} ${hoverClass}`
                    }`}
                  >
                    <Sparkles className="w-4 h-4 flex-shrink-0" />
                    <span className="truncate flex-1">{pl.name}</span>
                  </Link>
                </div>
              ))
            ) : (
              <div className={`px-2 py-1.5 text-xs ${textClass}`}>
                No smart playlists yet
              </div>
            )}
          </nav>
        )}
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
      {playlistMenu.state.isOpen && playlistMenu.state.item && (
        <PlaylistContextMenu
          playlist={playlistMenu.state.item}
          position={playlistMenu.state.position}
          onClose={playlistMenu.close}
          onRename={() => {
            const pl = playlistMenu.state.item!;
            setEditModal({ id: pl.id, name: pl.name, description: pl.description || '' });
          }}
          onMakeMixTape={() => {
            const pl = playlistMenu.state.item!;
            setMixtapeSource({ kind: 'playlist', id: pl.id, defaultName: pl.name });
            playlistMenu.close();
          }}
        />
      )}
      {smartPlaylistMenu.state.isOpen && smartPlaylistMenu.state.item && (
        <SmartPlaylistContextMenu
          playlist={smartPlaylistMenu.state.item}
          position={smartPlaylistMenu.state.position}
          onClose={smartPlaylistMenu.close}
          onEditRules={() => {
            setEditingSmartPlaylist(smartPlaylistMenu.state.item!);
            setShowSmartPlaylistBuilder(true);
            smartPlaylistMenu.close();
          }}
          onMakeMixTape={() => {
            const sp = smartPlaylistMenu.state.item!;
            setMixtapeSource({ kind: 'smart_playlist', id: sp.id, defaultName: sp.name });
            smartPlaylistMenu.close();
          }}
        />
      )}
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
      {showSmartPlaylistBuilder && (
        <SmartPlaylistBuilder
          playlist={editingSmartPlaylist}
          onClose={() => { setShowSmartPlaylistBuilder(false); setEditingSmartPlaylist(undefined); }}
          onSaved={(playlist) => {
            navigate(`/smart-playlists/${playlist.id}`);
            setShowSmartPlaylistBuilder(false);
            setEditingSmartPlaylist(undefined);
          }}
        />
      )}

      {/* Edit modal */}
      {editModal && (
        <PlaylistEditModal
          playlistId={editModal.id}
          initialName={editModal.name}
          initialDescription={editModal.description}
          isOpen={true}
          onClose={() => setEditModal(null)}
          onCreated={(id) => navigate(`/playlists/${id}`)}
        />
      )}
    </div>
  );
}
