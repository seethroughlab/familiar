/**
 * Sidebar - Persistent navigation sidebar.
 *
 * Sections: Library browsers, Collections (with counts), Playlists, Smart Playlists, Footer.
 */
import { useState } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  List, Users, Grid3X3, Smile, Map, Activity, Sparkles, FileText,
  Heart, Download, Gift,
  Settings, PanelLeftClose, PanelLeft,
  ListMusic, Clock, ChevronDown, ChevronUp,
} from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { useThemeStore } from '../../stores/themeStore';
import { useFavorites } from '../../hooks/useFavorites';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { useEphemeralPlaylistStore } from '../../stores/ephemeralPlaylistStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { playlistsApi, smartPlaylistsApi } from '../../api/client';
import type { Playlist } from '../../api/client';
import { SidebarPlaylistItem } from './SidebarPlaylistItem';

const LIBRARY_ITEMS = [
  { path: '/library/tracks', label: 'Tracks', icon: List },
  { path: '/library/artists', label: 'Artists', icon: Users },
  { path: '/library/albums', label: 'Albums', icon: Grid3X3 },
  { path: '/library/mood-grid', label: 'Mood Grid', icon: Smile },
  { path: '/library/music-map', label: 'Music Map', icon: Map },
  { path: '/library/explorer', label: '3D Explorer', icon: Activity },
  { path: '/library/discover', label: 'Discover', icon: Sparkles },
  { path: '/library/proposed-changes', label: 'Changes', icon: FileText },
];

const COLLECTION_ITEMS = [
  { path: '/favorites', label: 'Favorites', icon: Heart, countKey: 'favorites' as const },
  { path: '/downloads', label: 'Downloads', icon: Download, countKey: 'downloads' as const },
  { path: '/wishlist', label: 'Wishlist', icon: Gift, countKey: 'wishlist' as const },
];

export function Sidebar() {
  const location = useLocation();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useUIStore((s) => s.setSidebarCollapsed);
  const setShowSettings = useUIStore((s) => s.setShowSettings);

  // Section collapse state
  const [playlistsExpanded, setPlaylistsExpanded] = useState(true);
  const [smartPlaylistsExpanded, setSmartPlaylistsExpanded] = useState(true);

  // Collection counts
  const { total: favoritesCount } = useFavorites();
  const { total: downloadsCount } = useDownloadedTracks();
  const { isOffline } = useOfflineStatus();

  // Wishlist count
  const { data: wishlist } = useQuery({
    queryKey: ['wishlist'],
    queryFn: () => playlistsApi.getWishlist(),
    retry: isOffline ? false : 3,
  });
  const wishlistCount = wishlist?.tracks?.length ?? 0;

  const counts = {
    favorites: favoritesCount,
    downloads: downloadsCount,
    wishlist: wishlistCount,
  };

  // Playlists
  const { data: playlists } = useQuery({
    queryKey: ['playlists', 'ai'],
    queryFn: async () => {
      const data = await playlistsApi.list(true);
      return data.filter((p: Playlist) => p.is_auto_generated);
    },
    retry: isOffline ? false : 3,
  });

  // Smart playlists
  const { data: smartPlaylists } = useQuery({
    queryKey: ['smart-playlists'],
    queryFn: () => smartPlaylistsApi.list(),
    retry: isOffline ? false : 3,
  });

  // Ephemeral playlists
  const ephemeralPlaylists = useEphemeralPlaylistStore((s) => s.playlists);

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
  const isEphemeralActive = (id: string) => location.pathname === `/ephemeral/${id}`;

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
          {LIBRARY_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center justify-center mx-1 p-2 rounded-lg transition-colors ${
                isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
              }`}
              title={item.label}
            >
              <item.icon className="w-5 h-5" />
            </Link>
          ))}
          <div className={`mx-3 my-2 border-t ${dividerClass}`} />
          {COLLECTION_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center justify-center mx-1 p-2 rounded-lg transition-colors ${
                isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
              }`}
              title={`${item.label} (${counts[item.countKey]})`}
            >
              <item.icon className="w-5 h-5" />
            </Link>
          ))}
        </div>
        <div className={`border-t p-1 space-y-0.5 ${dividerClass}`}>
          <button
            onClick={() => setShowSettings(true)}
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
      </div>
    );
  }

  // Expanded sidebar
  return (
    <div className={`w-60 flex flex-col border-r ${bgClass} h-full`}>
      <div className="flex-1 overflow-y-auto min-h-0 py-2">
        {/* Library section */}
        <div className={`px-4 py-1 text-xs font-semibold uppercase tracking-wider ${sectionClass}`}>
          Library
        </div>
        <nav className="space-y-0.5 px-2 mt-1">
          {LIBRARY_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
                isActive(item.path) ? activeClass : `${textClass} ${hoverClass}`
              }`}
            >
              <item.icon className="w-4 h-4 flex-shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className={`mx-4 my-3 border-t ${dividerClass}`} />

        {/* Collections section */}
        <div className={`px-4 py-1 text-xs font-semibold uppercase tracking-wider ${sectionClass}`}>
          Collections
        </div>
        <nav className="space-y-0.5 px-2 mt-1">
          {COLLECTION_ITEMS.map((item) => (
            <Link
              key={item.path}
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
          ))}
        </nav>

        <div className={`mx-4 my-3 border-t ${dividerClass}`} />

        {/* Ephemeral (unsaved) playlists */}
        {ephemeralPlaylists.length > 0 && (
          <>
            <div className={`px-4 py-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider ${sectionClass}`}>
              <Clock className="w-3 h-3" />
              Unsaved
            </div>
            <nav className="space-y-0.5 px-2 mt-1">
              {ephemeralPlaylists.map((pl) => (
                <Link
                  key={pl.id}
                  to={`/ephemeral/${pl.id}`}
                  className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors border border-dashed ${
                    isEphemeralActive(pl.id)
                      ? 'border-amber-500/30 bg-amber-900/20 text-amber-300'
                      : `border-transparent ${textClass} ${hoverClass}`
                  }`}
                >
                  <ListMusic className="w-4 h-4 flex-shrink-0 text-amber-400" />
                  <span className="truncate flex-1">{pl.name}</span>
                  <span className={`text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>
                    {pl.tracks.length}
                  </span>
                </Link>
              ))}
            </nav>
            <div className={`mx-4 my-3 border-t ${dividerClass}`} />
          </>
        )}

        {/* Playlists section */}
        <button
          onClick={() => setPlaylistsExpanded(!playlistsExpanded)}
          className={`w-full flex items-center justify-between px-4 py-1 text-xs font-semibold uppercase tracking-wider ${sectionClass} ${hoverClass} rounded`}
        >
          <span>Playlists</span>
          {playlistsExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
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
        <button
          onClick={() => setSmartPlaylistsExpanded(!smartPlaylistsExpanded)}
          className={`w-full flex items-center justify-between px-4 py-1 text-xs font-semibold uppercase tracking-wider ${sectionClass} ${hoverClass} rounded`}
        >
          <span>Smart Playlists</span>
          {smartPlaylistsExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
        {smartPlaylistsExpanded && (
          <nav className="space-y-0.5 px-2 mt-1">
            {smartPlaylists && smartPlaylists.length > 0 ? (
              smartPlaylists.map((pl) => (
                <Link
                  key={pl.id}
                  to={`/smart-playlists/${pl.id}`}
                  className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${
                    isSmartPlaylistActive(pl.id) ? activeClass : `${textClass} ${hoverClass}`
                  }`}
                >
                  <Sparkles className="w-4 h-4 flex-shrink-0" />
                  <span className="truncate flex-1">{pl.name}</span>
                </Link>
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
            onClick={() => setShowSettings(true)}
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
    </div>
  );
}
