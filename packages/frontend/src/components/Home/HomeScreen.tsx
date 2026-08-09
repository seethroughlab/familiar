import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowUp,
  Brain,
  Compass,
  Heart,
  Home,
  Library,
  Loader2,
  MessageSquare,
  Music2,
  Play,
  RefreshCw,
  Settings2,
  Sparkles,
  Waves,
} from 'lucide-react';
import { libraryApi } from '../../api';
import { queryKeys } from '../../api/queryKeys';
import { STALE_TIME } from '../../api/queryDefaults';
import { useFavorites } from '../../hooks/useFavorites';
import { useDownloadedTracks } from '../../hooks/useDownloadedTracks';
import { useOfflineStatus } from '../../hooks/useOfflineStatus';
import { getSelectedProfileId } from '../../services/profileService';
import {
  getHomePreferences,
  getRecentDestinations,
  type HomeModuleId,
  useHomeStore,
} from '../../stores/homeStore';
import { usePlayerStore } from '../../stores/playerStore';
import { useThemeStore } from '../../stores/themeStore';
import { useUIStore } from '../../stores/uiStore';

const MODULE_LABELS: Record<HomeModuleId, string> = {
  resume: 'Resume / Continue',
  prompts: 'Prompt Onramp',
  'quick-picks': 'Quick Picks',
  discovery: 'Discovery Preview',
  'library-shortcuts': 'Library Shortcuts',
};

function HomeCard({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/70 shadow-[0_20px_80px_-40px_rgba(0,0,0,0.9)] backdrop-blur-sm">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-800/70 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">{title}</h2>
          {description && <p className="mt-1 text-sm text-zinc-400">{description}</p>}
        </div>
        {actions}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function ActionPill({
  to,
  onClick,
  icon: Icon,
  label,
  detail,
}: {
  to?: string;
  onClick?: () => void;
  icon: typeof Home;
  label: string;
  detail?: string;
}) {
  const className = 'flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-950/70 px-4 py-3 text-left transition hover:border-zinc-700 hover:bg-zinc-900/80';
  const content = (
    <>
      <div className="rounded-lg bg-zinc-800/80 p-2 text-zinc-200">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-zinc-100">{label}</div>
        {detail && <div className="truncate text-xs text-zinc-400">{detail}</div>}
      </div>
    </>
  );

  if (to) {
    return (
      <Link to={to} className={className}>
        {content}
      </Link>
    );
  }

  return (
    <button onClick={onClick} className={className}>
      {content}
    </button>
  );
}

export function HomeScreen() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const resolvedTheme = useThemeStore((state) => state.resolvedTheme);
  const { isOffline } = useOfflineStatus();
  const { total: favoritesCount } = useFavorites();
  const { total: downloadsCount } = useDownloadedTracks();
  const currentTrack = usePlayerStore((state) => state.currentTrack);
  const isPlaying = usePlayerStore((state) => state.isPlaying);
  const queue = usePlayerStore((state) => state.queue);
  const queueIndex = usePlayerStore((state) => state.queueIndex);
  const setIsPlaying = usePlayerStore((state) => state.setIsPlaying);
  const jumpToQueueIndex = usePlayerStore((state) => state.jumpToQueueIndex);
  const rightPanel = useUIStore((state) => state.rightPanel);
  const toggleRightPanel = useUIStore((state) => state.toggleRightPanel);
  const setShowFullPlayer = useUIStore((state) => state.setShowFullPlayer);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [showCustomize, setShowCustomize] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSelectedProfileId().then((id) => {
      if (!cancelled) setProfileId(id);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const preferencesByProfile = useHomeStore((state) => state.preferencesByProfile);
  const recentDestinationsByProfile = useHomeStore((state) => state.recentDestinationsByProfile);
  const setModuleEnabled = useHomeStore((state) => state.setModuleEnabled);
  const moveModule = useHomeStore((state) => state.moveModule);
  const resetPreferences = useHomeStore((state) => state.resetPreferences);

  const preferences = useMemo(
    () => getHomePreferences(profileId, preferencesByProfile),
    [preferencesByProfile, profileId]
  );
  const recentDestinations = useMemo(
    () => getRecentDestinations(profileId, recentDestinationsByProfile),
    [profileId, recentDestinationsByProfile]
  );

  const discoverQuery = useQuery({
    queryKey: queryKeys.libraryDiscover.all,
    queryFn: () => libraryApi.getDiscover({ recommendations_limit: 8 }),
    enabled: !isOffline,
    staleTime: STALE_TIME.LONG,
  });


  const activeModuleOrder = preferences.order.filter((moduleId) => preferences.enabled[moduleId]);

  const quickPicks = [
    {
      label: 'Favorites',
      detail: favoritesCount > 0 ? `${favoritesCount} saved tracks` : 'Your most-loved tracks',
      to: '/favorites',
      icon: Heart,
    },
    {
      label: 'Downloads',
      detail: downloadsCount > 0 ? `${downloadsCount} available offline` : 'Offline listening',
      to: '/downloads',
      icon: Waves,
    },
    {
      label: 'Recently Added',
      detail: discoverQuery.data
        ? `${discoverQuery.data.recently_added_count} tracks added recently`
        : 'Fresh arrivals in your library',
      to: '/library/discover',
      icon: Music2,
    },
    {
      label: 'Discover',
      detail: 'New artists, deep cuts, and unheard tracks',
      to: '/library/discover',
      icon: Compass,
    },
  ];

  const libraryShortcuts = [
    { label: 'Tracks', to: '/library/tracks', icon: Music2, detail: 'All tracks' },
    { label: 'Artists', to: '/library/artists', icon: Library, detail: 'Browse artists' },
    { label: 'Albums', to: '/library/albums', icon: Home, detail: 'Browse albums' },
    { label: 'Music Map', to: '/library/music-map', icon: Sparkles, detail: 'Explore by sound' },
  ];


  const handleResume = () => {
    if (queue.length === 0) return;
    if (currentTrack) {
      setIsPlaying(true);
      setShowFullPlayer(true);
      return;
    }
    jumpToQueueIndex(queueIndex >= 0 ? queueIndex : 0);
    setShowFullPlayer(true);
  };

  const chatAvailable = useUIStore((s) => s.chatSurfaceAvailable);


  const renderModule = (moduleId: HomeModuleId) => {
    switch (moduleId) {
      case 'resume':
        return (
          <HomeCard
            key={moduleId}
            title="Resume / Continue"
            description="Get back to the thread you were already following."
            actions={
              queue.length > 0 ? (
                <button
                  onClick={handleResume}
                  className="inline-flex items-center gap-2 rounded-lg bg-green-500 px-3 py-2 text-sm font-medium text-black transition hover:bg-green-400"
                >
                  <Play className="h-4 w-4 fill-current" />
                  {isPlaying ? 'Open player' : 'Resume queue'}
                </button>
              ) : null
            }
          >
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
              <div className="rounded-2xl border border-zinc-800 bg-gradient-to-br from-emerald-500/10 via-zinc-950/30 to-cyan-500/10 p-4">
                {currentTrack ? (
                  <div className="space-y-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-emerald-300/80">
                      Now Playing
                    </div>
                    <div className="text-xl font-semibold text-zinc-100">
                      {currentTrack.title || 'Unknown Title'}
                    </div>
                    <div className="text-sm text-zinc-400">
                      {currentTrack.artist || 'Unknown Artist'}
                      {currentTrack.album ? ` • ${currentTrack.album}` : ''}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={handleResume}
                        className="rounded-lg bg-emerald-400 px-3 py-2 text-sm font-medium text-black transition hover:bg-emerald-300"
                      >
                        {isPlaying ? 'Open full player' : 'Resume playback'}
                      </button>
                      <button
                        onClick={() => toggleRightPanel('queue')}
                        className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-900"
                      >
                        {rightPanel === 'queue' ? 'Hide queue' : 'Open queue'}
                      </button>
                    </div>
                  </div>
                ) : queue.length > 0 ? (
                  <div className="space-y-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-emerald-300/80">
                      Queue Ready
                    </div>
                    <div className="text-xl font-semibold text-zinc-100">
                      {queue.length} tracks queued
                    </div>
                    <div className="text-sm text-zinc-400">
                      Pick up where you left off without digging through the library.
                    </div>
                    <button
                      onClick={handleResume}
                      className="rounded-lg bg-emerald-400 px-3 py-2 text-sm font-medium text-black transition hover:bg-emerald-300"
                    >
                      Start queue
                    </button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="text-xs uppercase tracking-[0.2em] text-zinc-400">
                      Ready to Start
                    </div>
                    <div className="text-lg font-semibold text-zinc-100">
                      Nothing is queued yet.
                    </div>
                    <div className="text-sm text-zinc-400">
                      Use the prompt ideas below or jump into Favorites, Downloads, or Discover.
                    </div>
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <div className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
                  Recently Opened
                </div>
                {recentDestinations.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-zinc-800 px-4 py-6 text-sm text-zinc-500">
                    We&apos;ll keep recent views here as you move through Familiar.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {recentDestinations.map((destination) => (
                      <button
                        key={destination.route}
                        onClick={() => navigate(destination.route)}
                        className="flex w-full items-center justify-between rounded-xl border border-zinc-800 bg-zinc-950/70 px-4 py-3 text-left transition hover:border-zinc-700 hover:bg-zinc-900"
                      >
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-zinc-100">
                            {destination.label}
                          </div>
                          {destination.subtitle && (
                            <div className="truncate text-xs text-zinc-400">{destination.subtitle}</div>
                          )}
                        </div>
                        <div className="ml-4 text-xs text-zinc-500">
                          {new Date(destination.timestamp).toLocaleDateString(undefined, {
                            month: 'short',
                            day: 'numeric',
                          })}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </HomeCard>
        );

      case 'quick-picks':
        return (
          <HomeCard
            key={moduleId}
            title="Quick Picks"
            description="High-confidence next steps, using signals we already trust."
          >
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {quickPicks.map((item) => (
                <ActionPill
                  key={item.label}
                  to={item.to}
                  icon={item.icon}
                  label={item.label}
                  detail={item.detail}
                />
              ))}
            </div>
          </HomeCard>
        );

      case 'discovery':
        return (
          <HomeCard
            key={moduleId}
            title="Discovery Preview"
            description="A light preview of what Familiar thinks is worth exploring."
            actions={
              <Link
                to="/library/discover"
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-900"
              >
                <Compass className="h-4 w-4" />
                Open Discover
              </Link>
            }
          >
            {isOffline ? (
              <div className="rounded-xl border border-dashed border-zinc-800 px-4 py-6 text-sm text-zinc-500">
                Discovery preview is offline right now. Reconnect to load new releases and recommendations.
              </div>
            ) : discoverQuery.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-zinc-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading discovery preview...
              </div>
            ) : discoverQuery.data ? (
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
                    Recommended Artists
                  </div>
                  <div className="space-y-2">
                    {discoverQuery.data.recommended_artists.slice(0, 3).map((artist) => (
                      <button
                        key={artist.name}
                        onClick={() => navigate(`/library/artists/${encodeURIComponent(artist.name)}`)}
                        className="block w-full rounded-lg bg-zinc-900/80 px-3 py-2 text-left transition hover:bg-zinc-800"
                      >
                        <div className="text-sm font-medium text-zinc-100">{artist.name}</div>
                        <div className="text-xs text-zinc-400">via {artist.based_on_artist}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
                    Unheard Tracks
                  </div>
                  <div className="space-y-2">
                    {discoverQuery.data.unheard_tracks.slice(0, 3).map((track) => (
                      <button
                        key={track.id}
                        onClick={() => navigate('/library/discover')}
                        className="block w-full rounded-lg bg-zinc-900/80 px-3 py-2 text-left transition hover:bg-zinc-800"
                      >
                        <div className="text-sm font-medium text-zinc-100">
                          {track.title || 'Unknown Title'}
                        </div>
                        <div className="text-xs text-zinc-400">{track.artist || 'Unknown Artist'}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">
                    Deep Cuts
                  </div>
                  <div className="space-y-2">
                    {discoverQuery.data.deep_cuts.slice(0, 3).map((track) => (
                      <button
                        key={track.id}
                        onClick={() => navigate('/library/discover')}
                        className="block w-full rounded-lg bg-zinc-900/80 px-3 py-2 text-left transition hover:bg-zinc-800"
                      >
                        <div className="text-sm font-medium text-zinc-100">
                          {track.title || 'Unknown Title'}
                        </div>
                        <div className="text-xs text-zinc-400">{track.artist || 'Unknown Artist'}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-zinc-800 px-4 py-6 text-sm text-zinc-500">
                Discovery preview is temporarily unavailable.
              </div>
            )}
          </HomeCard>
        );

      case 'library-shortcuts':
        return (
          <HomeCard
            key={moduleId}
            title="Library Shortcuts"
            description="Stable launch points into Familiar’s main browsing surfaces."
          >
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {libraryShortcuts.map((item) => (
                <ActionPill
                  key={item.label}
                  to={item.to}
                  icon={item.icon}
                  label={item.label}
                  detail={item.detail}
                />
              ))}
            </div>
          </HomeCard>
        );
    }
  };

  return (
    <div className={resolvedTheme === 'light' ? 'bg-white text-zinc-900' : 'bg-black text-white'}>
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 md:px-6">
        <section className="rounded-3xl border border-zinc-800 bg-[radial-gradient(circle_at_top_left,_rgba(99,102,241,0.16),_transparent_38%),radial-gradient(circle_at_top_right,_rgba(34,197,94,0.14),_transparent_32%),linear-gradient(180deg,rgba(24,24,27,0.96),rgba(9,9,11,0.98))] p-6 shadow-[0_24px_120px_-56px_rgba(0,0,0,1)]">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-zinc-700/70 bg-zinc-900/70 px-3 py-1 text-xs uppercase tracking-[0.24em] text-zinc-400">
                <Sparkles className="h-3.5 w-3.5 text-purple-300" />
                Familiar Home
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-zinc-50 md:text-4xl">
                Pick up your listening without starting from scratch.
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-300 md:text-base">
                Home is here to help you resume momentum, choose a confident next play, or jump
                into chat with prompts that evolve with your library and taste.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setShowCustomize((value) => !value)}
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-900"
              >
                <Settings2 className="h-4 w-4" />
                Customize
              </button>
            </div>
          </div>

          {showCustomize && (
            <div className="mt-5 rounded-2xl border border-zinc-800 bg-zinc-950/70 p-4">
              <div className="mb-3 flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-zinc-100">Home modules</div>
                  <div className="text-xs text-zinc-400">
                    Light customization only: show, hide, reorder, and reset.
                  </div>
                </div>
                <button
                  onClick={() => resetPreferences(profileId)}
                  className="rounded-lg border border-zinc-700 px-3 py-2 text-xs text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-900"
                >
                  Reset defaults
                </button>
              </div>
              <div className="space-y-2">
                {preferences.order.map((moduleId) => (
                  <div
                    key={moduleId}
                    className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-3"
                  >
                    <label className="flex flex-1 items-center gap-3">
                      <input
                        type="checkbox"
                        checked={preferences.enabled[moduleId]}
                        onChange={(event) =>
                          setModuleEnabled(profileId, moduleId, event.target.checked)
                        }
                        className="h-4 w-4 rounded border-zinc-700 bg-zinc-950 text-green-500 focus:ring-green-500"
                      />
                      <span className="text-sm text-zinc-100">{MODULE_LABELS[moduleId]}</span>
                    </label>
                    <div className="flex gap-1">
                      <button
                        onClick={() => moveModule(profileId, moduleId, 'up')}
                        className="rounded-lg border border-zinc-700 p-2 text-zinc-300 transition hover:border-zinc-600 hover:bg-zinc-950"
                        aria-label={`Move ${MODULE_LABELS[moduleId]} up`}
                      >
                        <ArrowUp className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => moveModule(profileId, moduleId, 'down')}
                        className="rounded-lg border border-zinc-700 p-2 text-zinc-300 transition hover:border-zinc-600 hover:bg-zinc-950"
                        aria-label={`Move ${MODULE_LABELS[moduleId]} down`}
                      >
                        <ArrowDown className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        {activeModuleOrder.map(renderModule)}
      </div>
    </div>
  );
}
