/**
 * MobileMoreSheet - Bottom sheet with additional navigation items.
 *
 * Shows library browsers, collections, playlists, and utility items
 * that don't fit in the 4-item bottom nav bar.
 */
import { useNavigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  List, Grid3X3, Map, Sparkles, FileText,
  Download, Settings, Waves,
  ListMusic, Clock, X,
} from 'lucide-react';
import { useUIStore } from '../../stores/uiStore';
import { getAmbientSynthBridge } from '../../player/ambient/ambientSynthBridge';
import { useThemeStore } from '../../stores/themeStore';
import { useEphemeralPlaylistStore } from '../../stores/ephemeralPlaylistStore';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { playlistsApi, smartPlaylistsApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { offlineAwareRetry } from '../../api/queryDefaults';
import type { Playlist } from '../../api';

interface Props {
  onClose: () => void;
}

const LIBRARY_ITEMS = [
  { path: '/library/tracks', label: 'Tracks', icon: List },
  { path: '/library/albums', label: 'Albums', icon: Grid3X3 },
  { path: '/library/music-map', label: 'Music Map', icon: Map },
  { path: '/library/discover', label: 'Discover', icon: Sparkles },
  { path: '/library/proposed-changes', label: 'Changes', icon: FileText },
];

const COLLECTION_ITEMS = [
  { path: '/downloads', label: 'Downloads', icon: Download },
];

export function MobileMoreSheet({ onClose }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const resolvedTheme = useThemeStore((s) => s.resolvedTheme);
  const setShowSettings = useUIStore((s) => s.setShowSettings);
  const setShowAmbientScreen = useUIStore((s) => s.setShowAmbientScreen);
  const hasAmbientSynth = getAmbientSynthBridge() !== null;
  const { isOffline } = useOfflineStatus();

  const { data: playlists } = useQuery({
    queryKey: queryKeys.playlists.ai,
    queryFn: async () => {
      const data = await playlistsApi.list(true);
      return data.filter((p: Playlist) => p.is_auto_generated);
    },
    retry: offlineAwareRetry(isOffline),
  });

  const { data: smartPlaylists } = useQuery({
    queryKey: queryKeys.smartPlaylists.all,
    queryFn: () => smartPlaylistsApi.list(),
    retry: offlineAwareRetry(isOffline),
  });

  const ephemeralPlaylists = useEphemeralPlaylistStore((s) => s.playlists);

  const light = resolvedTheme === 'light';
  const isActive = (path: string) => location.pathname === path || location.pathname.startsWith(path + '/');

  const handleNav = (path: string) => {
    navigate(path);
    onClose();
  };


  const handleSettings = () => {
    setShowSettings(true);
    onClose();
  };

  const itemClass = (path: string) =>
    `flex items-center gap-3 px-4 py-3 transition-colors ${
      isActive(path)
        ? 'text-green-500'
        : light ? 'text-zinc-700 active:bg-zinc-100' : 'text-zinc-300 active:bg-zinc-800'
    }`;

  const sectionClass = `px-4 pt-4 pb-1 text-xs font-semibold uppercase tracking-wider ${
    light ? 'text-zinc-400' : 'text-zinc-500'
  }`;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Sheet */}
      <div
        className={`absolute bottom-0 left-0 right-0 rounded-t-2xl pb-safe-bottom max-h-[75vh] flex flex-col ${
          light ? 'bg-white' : 'bg-zinc-900'
        }`}
      >
        {/* Handle + close */}
        <div className="flex items-center justify-between px-4 pt-3 pb-1">
          <div className="w-8 h-1 bg-zinc-600 rounded-full mx-auto" />
          <button
            onClick={onClose}
            className={`absolute right-3 top-3 p-1.5 rounded-lg ${
              light ? 'hover:bg-zinc-100' : 'hover:bg-zinc-800'
            }`}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="overflow-y-auto min-h-0 flex-1 pb-4">
          {/* Library browsers */}
          <div className={sectionClass}>Library</div>
          {LIBRARY_ITEMS.map((item) => (
            <button key={item.path} onClick={() => handleNav(item.path)} className={itemClass(item.path)}>
              <item.icon className="w-5 h-5 flex-shrink-0" />
              <span>{item.label}</span>
            </button>
          ))}

          {/* Collections */}
          <div className={sectionClass}>Collections</div>
          {COLLECTION_ITEMS.map((item) => (
            <button key={item.path} onClick={() => handleNav(item.path)} className={itemClass(item.path)}>
              <item.icon className="w-5 h-5 flex-shrink-0" />
              <span>{item.label}</span>
            </button>
          ))}

          {/* Ephemeral playlists */}
          {ephemeralPlaylists.length > 0 && (
            <>
              <div className={sectionClass}>
                <Clock className="w-3 h-3 inline mr-1" />
                Unsaved
              </div>
              {ephemeralPlaylists.map((pl) => (
                <button
                  key={pl.id}
                  onClick={() => handleNav(`/ephemeral/${pl.id}`)}
                  className={itemClass(`/ephemeral/${pl.id}`)}
                >
                  <ListMusic className="w-5 h-5 flex-shrink-0 text-amber-400" />
                  <span className="flex-1 truncate">{pl.name}</span>
                  <span className={`text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>{pl.tracks.length}</span>
                </button>
              ))}
            </>
          )}

          {/* Playlists */}
          {playlists && playlists.length > 0 && (
            <>
              <div className={sectionClass}>Playlists</div>
              {playlists.map((pl) => (
                <button
                  key={pl.id}
                  onClick={() => handleNav(`/playlists/${pl.id}`)}
                  className={itemClass(`/playlists/${pl.id}`)}
                >
                  <ListMusic className="w-5 h-5 flex-shrink-0" />
                  <span className="flex-1 truncate">{pl.name}</span>
                  <span className={`text-xs ${light ? 'text-zinc-400' : 'text-zinc-500'}`}>{pl.track_count}</span>
                </button>
              ))}
            </>
          )}

          {/* Smart playlists */}
          {smartPlaylists && smartPlaylists.length > 0 && (
            <>
              <div className={sectionClass}>Smart Playlists</div>
              {smartPlaylists.map((pl) => (
                <button
                  key={pl.id}
                  onClick={() => handleNav(`/smart-playlists/${pl.id}`)}
                  className={itemClass(`/smart-playlists/${pl.id}`)}
                >
                  <Sparkles className="w-5 h-5 flex-shrink-0" />
                  <span className="flex-1 truncate">{pl.name}</span>
                </button>
              ))}
            </>
          )}

          {/* Ambient mode (mobile only, requires native synth) */}
          {hasAmbientSynth && (
            <>
              <div className={`my-2 mx-4 border-t ${light ? 'border-zinc-200' : 'border-zinc-800'}`} />
              <button
                onClick={() => { setShowAmbientScreen(true); onClose(); }}
                className={`flex items-center gap-3 px-4 py-3 w-full ${light ? 'text-purple-600 active:bg-purple-50' : 'text-purple-400 active:bg-zinc-800'}`}
              >
                <Waves className="w-5 h-5 flex-shrink-0" />
                <span>Ambient</span>
              </button>
            </>
          )}

          {/* Utility items */}
          <div className={`my-2 mx-4 border-t ${light ? 'border-zinc-200' : 'border-zinc-800'}`} />
          <button onClick={handleSettings} className={`flex items-center gap-3 px-4 py-3 w-full ${light ? 'text-zinc-700 active:bg-zinc-100' : 'text-zinc-300 active:bg-zinc-800'}`}>
            <Settings className="w-5 h-5 flex-shrink-0" />
            <span>Settings</span>
          </button>
        </div>
      </div>
    </div>
  );
}
